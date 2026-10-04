"""
คำถามเกี่ยวกับมาตราที่ตอบจากฐานข้อมูลได้ตรงๆ (ตัวบท / อยู่หมวดไหน / ยกเลิกหรือยัง / ไม่มีมาตรานี้)
ต้องไม่เรียก AI — ส่วนคำถามที่ต้องตีความ (สรุป เปรียบเทียบ ปรับใช้กับข้อเท็จจริง) ยังต้องไปที่ AI
"""

import helpers  # noqa: F401

import unittest
from unittest import mock

from legal_engine import database as db
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA


class TestSectionLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = LegalQA(HybridLegalRetriever(db.list_statutes()))

    def ask_without_ai(self, question):
        with mock.patch.object(qa_module, "_call_llm", side_effect=AssertionError("AI must not be called")):
            return self.qa.ask(question)

    def test_text_question_returns_exact_statute_text(self):
        r = self.ask_without_ai("มาตรา 420 บัญญัติว่าอย่างไร")
        self.assertEqual((r["status"], r["lookup"], r["provider"]), ("DIRECT", "text", "database"))
        self.assertIn(db.get_statute("CCC-420")["content"], r["answer"])

    def test_other_text_phrasings(self):
        for q in ("ม.193/30 ว่าอย่างไร", "ขอตัวบทมาตรา 653", "ตัวบทเต็มมาตรา 150"):
            self.assertEqual(self.ask_without_ai(q)["lookup"], "text", q)

    def test_where_question_uses_heading_path(self):
        r = self.ask_without_ai("มาตรา 420 อยู่ในหมวดอะไร")
        self.assertEqual(r["lookup"], "where")
        self.assertIn("ลักษณะ 5 ละเมิด › หมวด 1 ความรับผิดเพื่อละเมิด", r["answer"])
        self.assertIn("บรรพ 2 หนี้", r["answer"])
        self.assertIn("หน้า 67", r["answer"])

    def test_status_question_on_repealed_and_active(self):
        repealed = next(s for s in db.list_statutes() if s["status"] == "repealed")
        num = repealed["section"].replace("มาตรา ", "")
        if "ทวิ" in num:   # รูปแบบ "ทวิ" ไม่ได้อยู่ใน regex เลขมาตรา — ใช้มาตรายกเลิกที่เป็นเลขล้วน
            repealed = next(s for s in db.list_statutes() if s["status"] == "repealed" and "ทวิ" not in s["section"])
            num = repealed["section"].replace("มาตรา ", "")
        r = self.ask_without_ai(f"มาตรา {num} ยกเลิกแล้วหรือยัง")
        self.assertEqual(r["lookup"], "status")
        self.assertIn("ถูกยกเลิกแล้ว", r["answer"])
        r = self.ask_without_ai("มาตรา 420 ยังใช้อยู่ไหม")
        self.assertIn("ยังมีผลใช้บังคับ", r["answer"])

    def test_missing_section_answered_without_ai(self):
        r = self.ask_without_ai("มาตรา 9999 คืออะไร")
        self.assertEqual((r["status"], r["lookup"]), ("DIRECT", "missing"))
        self.assertIn("ไม่พบ มาตรา 9999", r["answer"])

    def test_amount_at_start_is_not_a_missing_section(self):
        found, missing = qa_module._section_refs("2000 บาทต้องมีหลักฐานการกู้ยืมไหม")
        self.assertEqual((found, missing), ([], []))

    def test_interpretive_questions_still_go_to_ai(self):
        """คำถามที่ต้องตีความต้องไม่ถูกตอบด้วยตัวบทเปล่าๆ"""
        for q in ("สรุปมาตรา 420 ให้หน่อย", "มาตรา 420 กับ 421 ต่างกันอย่างไร", "องค์ประกอบมาตรา 420 มีอะไรบ้าง",
                  "ยกตัวอย่างมาตรา 420", "ถ้าเพื่อนขับรถชนคน มาตรา 420 ใช้ได้ไหม", "มาตรา 193/30 อายุความกี่ปี",
                  "ยกเลิกสัญญาเช่าได้ไหมตามมาตรา 386"):
            found, missing = qa_module._section_refs(q)
            self.assertEqual(qa_module._lookup_kind(q, found, missing), "", q)

    def test_partly_missing_sections_go_to_ai_with_note(self):
        found, missing = qa_module._section_refs("มาตรา 420 กับมาตรา 9999 ต่างกันอย่างไร")
        self.assertEqual(([s["section"] for s in found], missing), (["มาตรา 420"], ["มาตรา 9999"]))
        self.assertEqual(qa_module._lookup_kind("มาตรา 420 กับมาตรา 9999 ต่างกันอย่างไร", found, missing), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
