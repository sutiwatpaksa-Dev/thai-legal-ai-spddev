"""ทดสอบ API ทุก endpoint กับสำเนาฐานข้อมูล (ไม่แตะฐานข้อมูลจริง)"""

import helpers  # noqa: F401

import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app as app_module
from legal_engine import qa as qa_module

client = TestClient(app_module.app)
CCC = "ประมวลกฎหมายแพ่งและพาณิชย์"


class TestStatutes(unittest.TestCase):
    def test_list_all(self):
        r = client.get("/api/statutes").json()
        self.assertGreaterEqual(r["total"], 1872)
        self.assertEqual(r["total"], len(r["statutes"]))

    def test_filter_category(self):
        r = client.get("/api/statutes", params={"category": CCC}).json()
        self.assertEqual(r["total"], 1872)
        self.assertTrue(all(s["category"] == CCC for s in r["statutes"]))

    def test_sorted_by_section_number(self):
        secs = [s["section"] for s in client.get("/api/statutes", params={"category": CCC}).json()["statutes"]]
        i = secs.index("มาตรา 193")
        self.assertEqual(secs[i + 1], "มาตรา 193/1")      # /1 ต่อจากมาตราหลัก ไม่ใช่เรียงแบบตัวอักษร
        self.assertLess(secs.index("มาตรา 9"), secs.index("มาตรา 10"))

    def test_text_query(self):
        r = client.get("/api/statutes", params={"q": "กู้ยืมเงิน"}).json()
        self.assertIn("มาตรา 653", [s["section"] for s in r["statutes"]])

    def test_get_one_and_404(self):
        self.assertEqual(client.get("/api/statutes/CCC-193-1").json()["section"], "มาตรา 193/1")
        self.assertEqual(client.get("/api/statutes/CCC-99999").status_code, 404)

    def test_categories(self):
        cats = {c["category"]: c["total"] for c in client.get("/api/categories").json()["categories"]}
        self.assertEqual(cats[CCC], 1872)

    def test_crud_cycle_and_reindex(self):
        body = {"id": "TEST-1", "category": "ทดสอบ", "title": "ทดสอบ", "section": "มาตรา 1",
                "content": "ข้อความทดสอบเฉพาะกิจคำว่าซูเปอร์โนวา"}
        self.assertEqual(client.post("/api/statutes", json=body).status_code, 201)
        self.assertEqual(client.post("/api/statutes", json=body).status_code, 409)
        hits = client.post("/api/search", json={"query": "ซูเปอร์โนวา"}).json()["results"]
        self.assertEqual(hits[0]["statute"]["id"], "TEST-1")
        r = client.put("/api/statutes/TEST-1", json={"status": "repealed"}).json()
        self.assertEqual(r["status"], "repealed")
        self.assertEqual(client.put("/api/statutes/TEST-1", json={"status": "bogus"}).status_code, 422)
        self.assertEqual(client.delete("/api/statutes/TEST-1").status_code, 204)
        self.assertEqual(client.delete("/api/statutes/TEST-1").status_code, 404)
        hits = client.post("/api/search", json={"query": "ซูเปอร์โนวา"}).json()["results"]
        self.assertNotIn("TEST-1", [h["statute"]["id"] for h in hits])

    def test_vercel_blocks_writes_and_history(self):
        body = {"id": "TEST-V", "category": "ทดสอบ", "title": "ทดสอบ", "section": "มาตรา 1", "content": "x"}
        with mock.patch.dict("os.environ", {"VERCEL": "1"}):
            self.assertEqual(client.post("/api/statutes", json=body).status_code, 403)
            self.assertEqual(client.put("/api/statutes/CCC-420", json={"content": "x"}).status_code, 403)
            self.assertEqual(client.delete("/api/statutes/CCC-420").status_code, 403)
            self.assertEqual(client.get("/api/history").status_code, 403)
            self.assertEqual(client.get("/api/statutes/CCC-420").status_code, 200)   # อ่านได้ตามปกติ
        self.assertIn("ละเมิด", client.get("/api/statutes/CCC-420").json()["title"])

    def test_invalid_id_rejected(self):
        bad = {"id": "bad id/../x", "category": "x", "title": "x", "section": "มาตรา 1", "content": "x"}
        self.assertEqual(client.post("/api/statutes", json=bad).status_code, 422)


class TestSearch(unittest.TestCase):
    def check_top(self, query, section, within=3):
        res = client.post("/api/search", json={"query": query, "top_k": 10}).json()["results"]
        top = [r["statute"]["section"] for r in res[:within]]
        self.assertIn(section, top, f"{query!r} -> {top}")

    def test_real_questions_find_right_section(self):
        self.check_top("กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร", "มาตรา 653")
        self.check_top("อายุความเรียกค่าเสียหายจากการทำละเมิด", "มาตรา 448")
        self.check_top("ผู้เยาว์ทำนิติกรรมต้องได้รับความยินยอมของผู้แทนโดยชอบธรรม", "มาตรา 21")
        self.check_top("มาตรา 420", "มาตรา 420", within=1)

    def test_empty_query(self):
        self.assertEqual(client.post("/api/search", json={"query": "  "}).json(), {"results": []})

    def test_top_k_bounds(self):
        self.assertEqual(client.post("/api/search", json={"query": "สัญญา", "top_k": 0}).status_code, 422)
        self.assertEqual(client.post("/api/search", json={"query": "สัญญา", "top_k": 500}).status_code, 422)


class TestAskEndpoint(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(client.post("/api/ask", json={"question": ""}).status_code, 422)
        self.assertEqual(client.post("/api/ask", json={"question": "x" * 2001}).status_code, 422)

    def test_saves_history_and_score(self):
        fake = {"answer": "ต้องมีหลักฐานเป็นหนังสือ", "citations": [
            {"section": "มาตรา 653", "quote": "การกู้ยืมเงินกว่าสองพันบาทขึ้นไปนั้น"}]}
        with mock.patch.object(qa_module, "_call_llm", return_value=fake):
            r = client.post("/api/ask", json={"question": "กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร"}).json()
        self.assertEqual(r["status"], "CITATIONS_VERIFIED")
        self.assertEqual(r["faithfulness_score"], 100.0)
        h = client.get(f"/api/history/{r['analysis_id']}").json()
        self.assertEqual((h["provider"], h["status"], h["statutes_cited"]), ("ollama-qa", "CITATIONS_VERIFIED", ["มาตรา 653"]))
        self.assertEqual(client.delete(f"/api/history/{r['analysis_id']}").status_code, 204)
        self.assertEqual(client.get(f"/api/history/{r['analysis_id']}").status_code, 404)


class TestRemovedAndStatus(unittest.TestCase):
    def test_removed_endpoints_are_gone(self):
        for path in ("/api/analyze", "/api/check-qa", "/api/qa"):
            self.assertIn(client.post(path, json={}).status_code, (404, 405), path)

    def test_status_reports_real_counts(self):
        s = client.get("/api/status").json()
        self.assertGreaterEqual(s["statutes"], 1872)
        self.assertIn("health", s["llm"])


class TestHealth(unittest.TestCase):
    """ป้ายสถานะต้องสะท้อนการเรียกโมเดลจริง ไม่ใช่แค่ server เปิดอยู่"""

    def setUp(self):
        app_module._llm_health.update(ok=None, error_code=None, message="", checked_at=None, source=None)
        self.ollama = mock.patch.object(qa_module, "LLM_PROVIDER", "ollama")
        self.ollama.start()

    def tearDown(self):
        self.ollama.stop()

    def test_probe_failure_turns_health_red(self):
        oom = RuntimeError('HTTP 500: {"error":"unable to allocate CUDA_Host buffer"}')
        with mock.patch.object(app_module, "_probe_ollama", side_effect=oom):
            h = client.get("/api/status", params={"probe": "true"}).json()["llm"]["health"]
        self.assertEqual((h["ok"], h["error_code"], h["source"]), (False, "LLM_OUT_OF_MEMORY", "probe"))
        self.assertNotIn("CUDA", h["message"])

    def test_probe_success_and_cache(self):
        with mock.patch.object(app_module, "_probe_ollama") as probe:
            client.get("/api/status", params={"probe": "true"})
            client.get("/api/status", params={"probe": "true"})   # ยังไม่หมดอายุ cache
        self.assertEqual(probe.call_count, 1)
        self.assertTrue(client.get("/api/status").json()["llm"]["health"]["ok"])

    def test_quick_status_does_not_probe(self):
        with mock.patch.object(app_module, "_probe_ollama") as probe:
            client.get("/api/status")
        probe.assert_not_called()

    def test_failed_ask_turns_health_red_immediately(self):
        app_module._set_health(True, source="probe")
        with mock.patch.object(qa_module, "_call_llm", side_effect=RuntimeError("cudaMalloc failed: out of memory")):
            r = client.post("/api/ask", json={"question": "กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร"}).json()
        self.assertEqual(r["status"], "LLM_ERROR")
        self.assertEqual((r["llm_health"]["ok"], r["llm_health"]["error_code"]), (False, "LLM_OUT_OF_MEMORY"))
        self.assertFalse(client.get("/api/status").json()["llm"]["health"]["ok"])
        self.assertTrue(r["retrieved_statutes"])

    def test_successful_ask_turns_health_green(self):
        fake = {"answer": "x", "citations": [{"section": "มาตรา 653", "quote": "การกู้ยืมเงินกว่าสองพันบาทขึ้นไปนั้น"}]}
        with mock.patch.object(qa_module, "_call_llm", return_value=fake):
            r = client.post("/api/ask", json={"question": "กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร"}).json()
        self.assertTrue(r["llm_health"]["ok"])


class TestFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = client.get("/").text
        cls.js = client.get("/static/js/app.js").text
        cls.css = client.get("/static/css/style.css").text

    def test_only_two_sections(self):
        self.assertEqual(re.findall(r'data-tab="([^"]+)"', self.html), ["tab-ask", "tab-statutes"])
        for gone in ("tab-analyzer", "tab-check-qa", "tab-guardrails", "tab-settings", "API Key"):
            self.assertNotIn(gone, self.html)

    def test_js_calls_only_existing_endpoints(self):
        used = set(re.findall(r'["`](/api/[a-z\-]+)', self.js))
        self.assertTrue(used)
        self.assertEqual(used - {"/api/ask", "/api/search", "/api/status", "/api/statutes", "/api/feedback"}, set())

    def test_no_hardcoded_scores_or_claims(self):
        self.assertNotRegex(self.js, r"faithfulness_score\s*[:=]\s*\d")
        self.assertNotIn("100% Grounded", self.html)

    def test_dynamic_text_is_escaped(self):
        """ข้อความจากฐานข้อมูลและ AI ต้องผ่าน escapeHtml ก่อนแสดง"""
        for code in ("escapeHtml(c.quote)", "escapeHtml(data.answer)", "highlight(escapeHtml(text), terms)",
                     "escapeHtml(data.error"):
            self.assertIn(code, self.js)
        self.assertNotIn("onclick=", self.js)                 # ไม่ใช้ inline handler กับ id จากข้อมูล

    def test_raw_errors_hidden(self):
        """error ดิบแสดงเฉพาะเมื่อ server ส่ง debug_error (โหมดดีบัก) และซ่อนใน <details>"""
        self.assertNotIn("err.message)}", self.js.replace("escapeHtml(err.message)}", ""))
        self.assertIn("data.debug_error ? `<details", self.js)

    def test_accessibility_basics(self):
        self.assertIn('aria-label="ค้นหาในคลังตัวบท', self.html)
        self.assertIn(":focus-visible", self.css)
        self.assertNotRegex(self.css, r"(?<!:not\(:focus-visible\)) \{\s*outline:\s*none")

    def test_one_batch_size_and_arabic_ui_numbers(self):
        self.assertEqual(len(re.findall(r"BATCH_SIZE\s*=", self.js)), 1)
        chips = re.findall(r'class="chip-btn"[^>]*>([^<]+)<', self.html)
        self.assertTrue(chips)
        self.assertFalse([c for c in chips if re.search("[๐-๙]", c)], "ป้ายใช้เลขอารบิก")
        self.assertNotIn("1755", self.html)

    def test_mobile_overflow_rules(self):
        mobile = self.css[self.css.index("@media (max-width: 760px)"):]
        self.assertIn(".kb-select { width: 100%; min-width: 0; }", mobile)
        self.assertIn("flex-wrap: nowrap", mobile)               # ชิปเลื่อนแนวนอน

    def test_html_ids_used_by_js_exist(self):
        ids = set(re.findall(r'getElementById\("([^"]+)"\)', self.js))
        missing = [i for i in ids if f'id="{i}"' not in self.html]
        self.assertEqual(missing, [])

    def test_css_classes_used_exist(self):
        for cls in ("chip-btn", "citation-card", "statute-card", "verification-banner", "repealed-badge"):
            self.assertIn(f".{cls}", self.css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
