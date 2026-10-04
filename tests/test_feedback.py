"""
ระบบความคิดเห็นผู้ใช้: ให้คะแนนคำตอบ / รีวิวเว็บไซต์ / แจ้งตัวบทผิด และหน้าผู้ดูแล
(ใช้ตาราง feedback ในสำเนาฐานข้อมูลชั่วคราว — ไม่เรียก Google Sheet จริง)
"""

import helpers  # noqa: F401

import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app as app_module
from legal_engine import database as db
from legal_engine import feedback

LOCAL = {"FEEDBACK_SCRIPT_URL": "", "FEEDBACK_SECRET": "", "VERCEL": ""}
ADMIN = {"X-Admin-Password": "test-admin-pass"}


class FeedbackTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)
        app_module._recent.clear()
        self.env = mock.patch.dict(os.environ, {**LOCAL, "ADMIN_PASSWORD": "test-admin-pass"})
        self.env.start()
        self.win = mock.patch.object(feedback, "_windows_user_env", return_value="")
        self.win.start()
        with db.get_conn() as conn:
            conn.execute("DELETE FROM feedback")

    def tearDown(self):
        self.win.stop()
        self.env.stop()

    def post(self, **body):
        return self.client.post("/api/feedback", json=body)


class TestSubmit(FeedbackTestCase):
    def test_three_kinds_are_saved(self):
        self.assertEqual(self.post(type="answer", rating=1, comment="ดีมาก", question="มาตรา 420",
                                   model="openai/gpt-oss-120b", answer_status="CITATIONS_VERIFIED").status_code, 201)
        self.assertEqual(self.post(type="site", rating=4, nickname="นักกฎหมายฝึกหัด").status_code, 201)
        self.assertEqual(self.post(type="statute", section="มาตรา 252", comment="มีหัวข้อติดท้าย").status_code, 201)
        rows = db.list_feedback()
        self.assertEqual(sorted(r["type"] for r in rows), ["answer", "site", "statute"])
        site = next(r for r in rows if r["type"] == "site")
        self.assertEqual((site["rating"], site["nickname"]), (4, "นักกฎหมายฝึกหัด"))

    def test_blank_nickname_is_anonymous(self):
        self.post(type="site", rating=5, nickname="   ")
        self.assertEqual(db.list_feedback()[0]["nickname"], feedback.ANONYMOUS)

    def test_validation(self):
        self.assertEqual(self.post(type="answer", rating=5).status_code, 422)     # คำตอบ: 1/-1 เท่านั้น
        self.assertEqual(self.post(type="site").status_code, 422)                 # รีวิวต้องมีดาว
        self.assertEqual(self.post(type="site", rating=6).status_code, 422)
        self.assertEqual(self.post(type="statute", section="มาตรา 1").status_code, 422)   # ต้องอธิบาย
        self.assertEqual(self.post(type="other", rating=1).status_code, 422)
        self.assertEqual(self.post(type="site", rating=5, comment="x" * 1001).status_code, 422)
        self.assertEqual(db.list_feedback(), [])

    def test_no_personal_data_columns(self):
        """ไม่มีที่เก็บ IP อีเมล หรือเบอร์โทร"""
        for col in ("ip", "email", "phone"):
            self.assertNotIn(col, db.FEEDBACK_COLUMNS)

    def test_honeypot_is_ignored_silently(self):
        r = self.post(type="site", rating=5, website="http://spam.example")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(db.list_feedback(), [])

    def test_rate_limit(self):
        for _ in range(app_module.FEEDBACK_LIMIT):
            self.assertEqual(self.post(type="site", rating=5).status_code, 201)
        self.assertEqual(self.post(type="site", rating=5).status_code, 429)

    def test_disabled_on_vercel_without_sheet(self):
        """บน Vercel ฐานข้อมูลใน /tmp หาย — ห้ามรับข้อมูลถ้ายังไม่ได้ตั้งค่า Google Sheet"""
        with mock.patch.dict(os.environ, {"VERCEL": "1"}):
            self.assertFalse(feedback.enabled())
            self.assertEqual(self.post(type="site", rating=5).status_code, 503)
            self.assertFalse(self.client.get("/api/status").json()["feedback"]["enabled"])


class TestSheetBackend(FeedbackTestCase):
    def test_sheet_payload_and_formula_injection_guard(self):
        sent = []

        class FakeResp:
            def __init__(self, data): self.data = data
            def read(self): return json.dumps(self.data).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout):
            sent.append(json.loads(req.data.decode("utf-8")))
            return FakeResp({"ok": True})

        with mock.patch.dict(os.environ, {"FEEDBACK_SCRIPT_URL": "https://script.example/exec",
                                          "FEEDBACK_SECRET": "s3cret", "VERCEL": "1"}), \
             mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(feedback.backend(), "sheet")
            r = self.post(type="answer", rating=-1, comment="=HYPERLINK(\"http://evil\")", nickname="@me")
        self.assertEqual(r.status_code, 201)
        body = sent[0]
        self.assertEqual((body["secret"], body["action"]), ("s3cret", "add"))
        self.assertEqual(body["row"]["comment"], "'=HYPERLINK(\"http://evil\")")
        self.assertEqual(body["row"]["nickname"], "'@me")
        self.assertEqual(body["row"]["rating"], -1)          # ตัวเลขไม่ถูกแปลงเป็นข้อความ
        self.assertEqual(db.list_feedback(), [])             # ไม่ได้เขียนลง SQLite

    def test_sheet_failure_is_502(self):
        import urllib.error
        with mock.patch.dict(os.environ, {"FEEDBACK_SCRIPT_URL": "https://script.example/exec", "FEEDBACK_SECRET": "s"}), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            self.assertEqual(self.post(type="site", rating=3).status_code, 502)


class TestAdmin(FeedbackTestCase):
    def test_requires_password(self):
        self.assertEqual(self.client.get("/api/admin/feedback").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/feedback", headers={"X-Admin-Password": "wrong"}).status_code, 401)

    def test_disabled_without_admin_password(self):
        with mock.patch.dict(os.environ, {"ADMIN_PASSWORD": ""}):
            self.assertEqual(self.client.get("/api/admin/feedback", headers=ADMIN).status_code, 503)

    def test_lockout_after_wrong_passwords(self):
        for _ in range(app_module.ADMIN_FAIL_LIMIT):
            self.client.get("/api/admin/feedback", headers={"X-Admin-Password": "wrong"})
        self.assertEqual(self.client.get("/api/admin/feedback", headers=ADMIN).status_code, 429)

    def test_stats(self):
        self.post(type="answer", rating=1, model="openai/gpt-oss-120b")
        self.post(type="answer", rating=-1, model="openai/gpt-oss-120b")
        self.post(type="answer", rating=1, model="qwen/qwen3.8-27b")
        self.post(type="site", rating=5)
        self.post(type="site", rating=2)
        self.post(type="statute", section="มาตรา 252", comment="หัวข้อติดท้าย")
        data = self.client.get("/api/admin/feedback", headers=ADMIN).json()
        s = data["stats"]
        self.assertEqual((data["backend"], s["total"]), ("local", 6))
        self.assertEqual(s["by_type"], {"answer": 3, "site": 2, "statute": 1})
        self.assertEqual((s["site_average"], s["site_count"]), (3.5, 2))
        self.assertEqual(s["answer_by_model"]["openai/gpt-oss-120b"], {"up": 1, "down": 1})
        self.assertEqual(data["rows"][0]["type"], "statute")   # ล่าสุดก่อน

    def test_admin_page_served(self):
        r = self.client.get("/admin")
        self.assertEqual(r.status_code, 200)
        self.assertIn("รหัสผ่านผู้ดูแล", r.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
