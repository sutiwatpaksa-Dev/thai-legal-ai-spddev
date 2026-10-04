"""
ทดสอบการเชื่อมต่อ Groq ด้วย client จำลอง (ไม่เรียก API จริง ไม่กินโควตา)
"""

import helpers  # noqa: F401

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

import app as app_module
from legal_engine import claude_llm
from legal_engine import database as db
from legal_engine import groq_llm
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA

QUOTE_653 = "การกู้ยืมเงินกว่าสองพันบาทขึ้นไปนั้น"


def fake_completion(payload, finish_reason="stop"):
    msg = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)])


class FakeGroq:
    def __init__(self, response):
        self.calls = []
        self._response = response
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


ANSWER_653 = {"answer": "ต้องมีหลักฐานเป็นหนังสือเมื่อกู้เกินสองพันบาท",
              "citations": [{"section": "มาตรา 653", "quote": QUOTE_653}], "insufficient": False}


class TestCallGroq(unittest.TestCase):
    def call(self, response, summary=False, model=""):
        fake = FakeGroq(response)
        with mock.patch.object(groq_llm, "_get_client", return_value=fake), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "placeholder-not-a-real-key"}):
            out = groq_llm.call_groq("SYS", "USER", summary=summary, model=model)
        return out, fake.calls[0]

    def test_request_shape(self):
        out, req = self.call(fake_completion(ANSWER_653))
        self.assertEqual(out["answer"], ANSWER_653["answer"])
        self.assertEqual(req["model"], "openai/gpt-oss-120b")
        fmt = req["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIs(fmt["json_schema"]["strict"], True)
        self.assertIs(fmt["json_schema"]["schema"], claude_llm.ANSWER_SCHEMA)
        self.assertEqual(req["messages"], [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}])

    def test_summary_schema_and_chosen_model(self):
        _, req = self.call(fake_completion({}), summary=True, model="qwen/qwen3.8-27b")
        self.assertEqual(req["model"], "qwen/qwen3.8-27b")
        self.assertIs(req["response_format"]["json_schema"]["schema"], claude_llm.SUMMARY_SCHEMA)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):
            self.call(fake_completion({}), model="llama-something")

    def test_truncated_output_raises(self):
        with self.assertRaises(RuntimeError):
            self.call(fake_completion({}, finish_reason="length"))

    def test_every_model_has_label_and_description(self):
        self.assertEqual(set(groq_llm.GROQ_MODELS), {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"})
        for info in groq_llm.GROQ_MODELS.values():
            self.assertTrue(info["label"] and info["description"])


class TestGroqPipeline(unittest.TestCase):
    def test_end_to_end_with_chosen_model(self):
        fake = FakeGroq(fake_completion(ANSWER_653))
        qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        with mock.patch.object(qa_module, "LLM_PROVIDER", "groq"), \
             mock.patch.object(groq_llm, "_get_client", return_value=fake), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "placeholder-not-a-real-key"}):
            r = qa.ask("กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร", model="openai/gpt-oss-20b")
        self.assertEqual((r["provider"], r["model"], r["status"]), ("groq", "openai/gpt-oss-20b", "CITATIONS_VERIFIED"))
        self.assertEqual(fake.calls[0]["model"], "openai/gpt-oss-20b")

    def test_missing_key_is_clear_auth_error(self):
        fake = FakeGroq(fake_completion(ANSWER_653))
        qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        with mock.patch.object(qa_module, "LLM_PROVIDER", "groq"), \
             mock.patch.object(groq_llm, "_get_client", return_value=fake), \
             mock.patch.object(groq_llm, "_windows_user_env", return_value=""), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            r = qa.ask("กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร")
        self.assertEqual((r["status"], r["error_code"]), ("LLM_ERROR", "LLM_AUTH"))
        self.assertEqual(fake.calls, [])            # ไม่เรียก API เมื่อไม่มี key
        self.assertTrue(r["retrieved_statutes"])    # ตัวบทที่ค้นได้ยังส่งกลับให้อ่าน

    def test_model_ignored_for_other_providers(self):
        with mock.patch.object(qa_module, "LLM_PROVIDER", "ollama"):
            self.assertEqual(qa_module.active_model("answer", ""), qa_module.LLM_MODEL)

    def test_rate_limit_error_code(self):
        class RateLimitError(Exception):
            pass
        self.assertEqual(qa_module.classify_llm_error(RateLimitError("Error code: 429"))[0], "LLM_RATE_LIMIT")


class TestGroqApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_status_lists_models_with_descriptions(self):
        with mock.patch.object(qa_module, "LLM_PROVIDER", "groq"), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "placeholder-not-a-real-key"}):
            llm = self.client.get("/api/status").json()["llm"]
        self.assertEqual(llm["provider"], "groq")
        self.assertTrue(llm["configured"])
        self.assertEqual([m["id"] for m in llm["models"]], list(groq_llm.GROQ_MODELS))
        self.assertTrue(all(m["description"] for m in llm["models"]))

    def test_unknown_model_is_400(self):
        with mock.patch.object(qa_module, "LLM_PROVIDER", "groq"):
            r = self.client.post("/api/ask", json={"question": "มาตรา 420", "model": "not-a-model"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
