"""ทดสอบโหมดสรุปมาตรา (จำลองผลจาก LLM — ผลคงที่)"""

import helpers  # noqa: F401

import unittest
from unittest import mock

from legal_engine import database as db
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA, _explicit_sections, _summary_context

Q251 = "ผู้ทรงบุริมสิทธิย่อมทรงไว้ซึ่งสิทธิเหนือทรัพย์สินของลูกหนี้"
Q253 = "ค่าภาษีอากร และเงินที่ลูกจ้างมีสิทธิได้รับเพื่อการงานที่ได้ทำให้แก่ลูกหนี้ซึ่งเป็นนายจ้าง"


class TestSummaryParsing(unittest.TestCase):
    def test_question_section_forms(self):
        for q in ["สรุปเนื้อหา บท 251 ให้หน่อย", "สรุป มาตรา 251", "สรุป ม.251", "สรุป ม 251", "สรุปมาตรา ๒๕๑",
                  "สรุปมาตร 251 ให้เข้าใจ สั้นๆ หน่อย"]:   # พิมพ์ตก "มาตร" (จากการใช้งานจริง)
            self.assertEqual([s["id"] for s in _explicit_sections(q)], ["CCC-251"], q)

    def test_context_includes_neighbours_from_same_part(self):
        ctx = [s["section"] for s in _summary_context([db.get_statute("CCC-251")])]
        self.assertEqual(ctx[0], "มาตรา 251")
        self.assertIn("มาตรา 253", ctx)      # รายการบุริมสิทธิสามัญจริง (ค่าภาษี ค่าจ้าง ...)
        self.assertLessEqual(len(ctx), qa_module.SUMMARY_CONTEXT)

    def test_context_includes_cross_referenced_section(self):
        ctx = [s["section"] for s in _summary_context([db.get_statute("CCC-224")])]
        self.assertIn("มาตรา 7", ctx)        # ม.224 อ้าง "ตามมาตรา ๗"


class TestSummaryMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = LegalQA(HybridLegalRetriever(db.list_statutes()))

    def ask(self, out, q="สรุปเนื้อหา บท 251 ให้หน่อย"):
        with mock.patch.object(qa_module, "_call_llm", return_value=out) as m:
            r = self.qa.ask(q)
        return r, m

    def test_auto_mode_and_prompt(self):
        r, m = self.ask({"title": "t", "summary": "s", "key_points": [
            {"heading": "ผู้มีสิทธิ", "explanation": "e", "section": "มาตรา 251", "quote": Q251}]})
        self.assertEqual(r["mode"], "summary")
        self.assertIs(m.call_args.kwargs["system_prompt"], qa_module.SUMMARY_PROMPT)
        self.assertEqual(r["status"], "CITATIONS_VERIFIED")
        self.assertEqual(r["summary"]["key_points"][0]["source_page"], 44)
        self.assertIn("ประเด็นหลัก", r["answer"])

    def test_point_handling_for_bad_quotes(self):
        """
        พฤติกรรมที่ผู้ใช้เลือก: ถ้ามีคำอ้างอิงตกแม้แต่ข้อเดียว และตอบใหม่แล้วยังไม่ผ่าน ระบบจะไม่ตอบ (ABSTAIN)
        เพื่อป้องกันไม่ให้ผู้ใช้อ่านเนื้อหาที่ยกข้อความเท็จ
        """
        r, _ = self.ask({"title": "t", "summary": "s",
                         "key_points": [{"heading": "จริง", "explanation": "", "section": "มาตรา 251", "quote": Q251},
                                        {"heading": "แต่ง", "explanation": "x", "section": "มาตรา 251", "quote": "ข้อความที่ไม่มีจริง"}],
                         "notes": [{"point": "รายการจริง", "section": "มาตรา 253", "quote": Q253},
                                   {"point": "มาตรานอกบริบท", "section": "มาตรา 999", "quote": Q253}]})
        self.assertEqual(r["status"], "ABSTAIN")
        self.assertNotIn("summary", r)
        self.assertTrue(r["guardrails"]["rejected_citations"])

    def test_invented_section_in_example_is_flagged(self):
        r, _ = self.ask({"title": "t", "summary": "s", "example": "ตามมาตรา 9999 ลูกจ้างได้ก่อน",
                         "key_points": [{"heading": "h", "explanation": "", "section": "มาตรา 251", "quote": Q251}]})
        self.assertEqual(r["guardrails"]["unsupported_sections_in_answer"], ["มาตรา 9999"])
        self.assertEqual(r["status"], "ABSTAIN")

    def test_example_numbers_do_not_trigger_omission_check(self):
        """ตัวเลขสมมติในตัวอย่าง (เช่น 1 ล้านบาท) ไม่ใช่เงื่อนไขของตัวบท จึงไม่ต้องตรวจความครบ"""
        r, m = self.ask({"title": "t", "summary": "s", "example": "บ้านราคา 1,000,000 บาท หนี้ 3,000,000 บาท",
                         "key_points": [{"heading": "h", "explanation": "", "section": "มาตรา 253", "quote": Q253}]})
        self.assertEqual(m.call_count, 1)
        self.assertEqual(r["guardrails"]["omitted_conditions"], [])

    def test_no_verified_point_abstains(self):
        r, _ = self.ask({"title": "t", "summary": "s",
                         "key_points": [{"heading": "h", "section": "มาตรา 251", "quote": "ไม่มีจริง"}]})
        self.assertEqual(r["status"], "ABSTAIN")
        self.assertNotIn("summary", r)

    def test_short_request_gets_length_hint_and_full_context(self):
        r, m = self.ask({"title": "t", "summary": "s", "key_points": [
            {"heading": "h", "explanation": "", "section": "มาตรา 251", "quote": Q251}]},
            q="สรุปมาตร 251 ให้เข้าใจ สั้นๆ หน่อย")
        self.assertEqual(m.call_args.args[2], qa_module.SHORT_SUMMARY_FEEDBACK)
        self.assertGreater(len(r["retrieved_statutes"]), 1)      # ได้มาตราข้างเคียงด้วย ไม่ใช่แค่ 251

    def test_normal_summary_has_no_length_hint(self):
        _, m = self.ask({"title": "t", "summary": "s", "key_points": [
            {"heading": "h", "explanation": "", "section": "มาตรา 251", "quote": Q251}]})
        self.assertEqual(m.call_args.args[2], "")

    def test_plain_question_stays_answer_mode(self):
        with mock.patch.object(qa_module, "_call_llm", return_value={"answer": "", "citations": []}) as m:
            r = self.qa.ask("มาตรา 251 บัญญัติว่าอย่างไร")
        self.assertEqual(r["mode"], "answer")
        self.assertIs(m.call_args.kwargs["system_prompt"], qa_module.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
