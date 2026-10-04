"""
ทดสอบการเชื่อมต่อ Claude API ด้วย client จำลอง (ไม่เรียก API จริง ไม่เสียค่าใช้จ่าย)
"""

import helpers  # noqa: F401

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from legal_engine import claude_llm
from legal_engine import database as db
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA


def fake_response(payload, stop_reason="end_turn", category=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


class FakeClient:
    def __init__(self, response):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._response = response

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class TestCallClaude(unittest.TestCase):
    def call(self, response, summary=False):
        fake = FakeClient(response)
        with mock.patch.object(claude_llm, "_get_client", return_value=fake):
            out = claude_llm.call_claude("SYS", "USER", summary=summary)
        return out, fake.calls[0]

    def test_request_shape(self):
        out, req = self.call(fake_response({"answer": "a", "citations": [], "insufficient": False}))
        self.assertEqual(out["answer"], "a")
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["output_config"]["effort"], "high")
        self.assertIs(req["output_config"]["format"]["schema"], claude_llm.ANSWER_SCHEMA)
        self.assertEqual(req["system"], "SYS")
        self.assertEqual(req["messages"], [{"role": "user", "content": "USER"}])
        self.assertNotIn("thinking", req)          # Opus 5.5: thinking เปิดเสมอ ไม่ต้องส่ง
        self.assertNotIn("temperature", req)       # sampling params ถูกถอดบนโมเดลนี้

    def test_summary_schema(self):
        payload = {"title": "t", "summary": "s", "key_points": [], "example": "", "notes": [], "insufficient": False}
        out, req = self.call(fake_response(payload), summary=True)
        self.assertIs(req["output_config"]["format"]["schema"], claude_llm.SUMMARY_SCHEMA)
        self.assertEqual(out["title"], "t")

    def test_refusal_raises(self):
        with self.assertRaises(claude_llm.ClaudeRefusal):
            self.call(fake_response({}, stop_reason="refusal", category="cyber"))

    def test_truncated_output_raises(self):
        with self.assertRaises(RuntimeError):
            self.call(fake_response({}, stop_reason="max_tokens"))

    def test_schemas_are_strict(self):
        """structured outputs ต้องมี additionalProperties: false และ required ครบทุก field"""
        def walk(s):
            if s.get("type") == "object":
                self.assertIs(s["additionalProperties"], False)
                self.assertEqual(set(s["required"]), set(s["properties"]))
                for v in s["properties"].values():
                    walk(v)
            if s.get("type") == "array":
                walk(s["items"])
        walk(claude_llm.ANSWER_SCHEMA)
        walk(claude_llm.SUMMARY_SCHEMA)


class TestProviderSelection(unittest.TestCase):
    def test_key_from_windows_user_settings_is_used(self):
        """terminal ใน IDE ที่เปิดก่อน setx ไม่มีตัวแปรใหม่ — ต้องอ่านจากค่าระดับผู้ใช้ได้"""
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}), \
             mock.patch.object(claude_llm, "_windows_user_env", return_value="placeholder-not-a-real-key"), \
             mock.patch.object(qa_module, "LLM_PROVIDER", "auto"):
            self.assertEqual(qa_module.active_provider(), "anthropic")

    def test_auto_without_credentials_uses_ollama(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}), \
             mock.patch.object(claude_llm, "_windows_user_env", return_value=""), \
             mock.patch.object(qa_module, "LLM_PROVIDER", "auto"):
            self.assertEqual(qa_module.active_provider(), "ollama")
            self.assertEqual(qa_module.active_model(), qa_module.LLM_MODEL)

    def test_auto_with_credentials_uses_claude(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "placeholder-not-a-real-key"}), \
             mock.patch.object(qa_module, "LLM_PROVIDER", "auto"):
            self.assertEqual(qa_module.active_provider(), "anthropic")
            self.assertEqual(qa_module.active_model(), "claude-opus-5-5")

    def test_end_to_end_through_claude_path(self):
        """ask() -> _call_llm -> call_claude -> ตรวจอ้างอิงเหมือนเดิม"""
        quote = "การกู้ยืมเงินกว่าสองพันบาทขึ้นไปนั้น"
        fake = FakeClient(fake_response({"answer": "ต้องมีหลักฐานเป็นหนังสือเมื่อกู้เกินสองพันบาท",
                                         "citations": [{"section": "มาตรา 653", "quote": quote}],
                                         "insufficient": False}))
        qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        with mock.patch.object(qa_module, "LLM_PROVIDER", "anthropic"), \
             mock.patch.object(claude_llm, "_get_client", return_value=fake):
            r = qa.ask("กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร")
        self.assertEqual((r["provider"], r["model"], r["status"]), ("anthropic", "claude-opus-5-5", "CITATIONS_VERIFIED"))
        self.assertIn("มาตรา 653", fake.calls[0]["messages"][0]["content"])   # ตัวบทจริงถูกส่งไปด้วย

    def test_refusal_becomes_llm_error(self):
        fake = FakeClient(fake_response({}, stop_reason="refusal"))
        qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        with mock.patch.object(qa_module, "LLM_PROVIDER", "anthropic"), \
             mock.patch.object(claude_llm, "_get_client", return_value=fake):
            r = qa.ask("กู้ยืมเงินเกินสองพันบาทต้องมีหลักฐานอะไร")
        self.assertEqual((r["status"], r["error_code"]), ("LLM_ERROR", "LLM_REFUSED"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
