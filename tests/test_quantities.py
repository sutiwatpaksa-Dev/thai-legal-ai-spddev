"""ทดสอบการตรวจความครบของเงื่อนไข (ระยะเวลา/จำนวนเงิน/ร้อยละ) ในคำตอบ"""

import helpers  # noqa: F401

import unittest
from unittest import mock

from legal_engine import database as db
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA
from legal_engine.quantities import extract, omitted, thai_number


class TestThaiNumbers(unittest.TestCase):
    def test_words_and_digits(self):
        cases = {"สองพัน": 2000, "สิบห้า": 15, "ยี่สิบเอ็ด": 21, "สิบ": 10, "หนึ่งร้อย": 100,
                 "สามสิบ": 30, "๓": 3, "2,000": 2000, "๑๒": 12}
        for text, value in cases.items():
            self.assertEqual(thai_number(text), value, text)

    def test_extract_legal_phrases(self):
        self.assertEqual(extract("ขาดอายุความเมื่อพ้นปีหนึ่งนับแต่วันที่รู้ หรือเมื่อพ้นสิบปี"), {(1, "ปี"), (10, "ปี")})
        self.assertEqual(extract("การกู้ยืมเงินกว่าสองพันบาทขึ้นไป"), {(2000, "บาท")})
        self.assertEqual(extract("ให้ใช้อัตราร้อยละสามต่อปี"), {(3, "ร้อยละ")})
        self.assertEqual(extract("ไม่มีตัวเลข"), set())


class TestOmitted(unittest.TestCase):
    def test_real_wrong_answer_448(self):
        """คำตอบผิดที่ qwen2.5:7b เคยให้จริง ต้องถูกจับได้"""
        c = db.get_statute("CCC-448")["content"]
        self.assertEqual(omitted("อายุความเรียกค่าเสียหายจากการทำละเมิดเป็น 10 ปี นับแต่วันทำละเมิด", c), {(1, "ปี")})

    def test_complete_answers_pass(self):
        self.assertEqual(omitted("1 ปีนับแต่รู้ หรือ 10 ปีนับแต่วันทำละเมิด", db.get_statute("CCC-448")["content"]), set())
        self.assertEqual(omitted("กู้เกินสองพันบาทต้องมีหลักฐานเป็นหนังสือ", db.get_statute("CCC-653")["content"]), set())
        self.assertEqual(omitted("ร้อยละสามต่อปี", db.get_statute("CCC-7")["content"]), set())

    def test_units_not_mentioned_are_not_required(self):
        """คำตอบที่ไม่พูดถึงระยะเวลาเลย ไม่ถูกบังคับให้ระบุระยะเวลา"""
        self.assertEqual(omitted("ต้องรับผิดใช้ค่าสินไหมทดแทน", db.get_statute("CCC-448")["content"]), set())


class TestRetryOnOmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        cls.q = "อายุความเรียกค่าเสียหายจากการทำละเมิดกี่ปี"
        cls.quote10 = "หรือเมื่อพ้นสิบปีนับแต่วันทำละเมิด"
        cls.quote1 = "ขาดอายุความเมื่อพ้นปีหนึ่งนับแต่วันที่ผู้ต้องเสียหายรู้ถึงการละเมิด"

    def test_retry_fixes_incomplete_answer(self):
        first = {"answer": "10 ปี นับแต่วันทำละเมิด", "citations": [{"section": "มาตรา 448", "quote": self.quote10}]}
        second = {"answer": "1 ปีนับแต่รู้ หรือ 10 ปีนับแต่วันทำละเมิด", "citations": [
            {"section": "มาตรา 448", "quote": self.quote1}, {"section": "มาตรา 448", "quote": self.quote10}]}
        with mock.patch.object(qa_module, "_call_llm", side_effect=[first, second]) as m:
            r = self.qa.ask(self.q)
        self.assertEqual(m.call_count, 2)
        self.assertIn("1 ปี", m.call_args_list[1].args[2])   # feedback บอกสิ่งที่ขาด
        self.assertEqual(r["status"], "CITATIONS_VERIFIED")
        self.assertEqual(r["guardrails"]["omitted_conditions"], [])

    def test_still_incomplete_is_flagged_partial(self):
        bad = {"answer": "10 ปี นับแต่วันทำละเมิด", "citations": [{"section": "มาตรา 448", "quote": self.quote10}]}
        with mock.patch.object(qa_module, "_call_llm", side_effect=[bad, bad]):
            r = self.qa.ask(self.q)
        self.assertEqual(r["status"], "CITATIONS_PARTIAL")
        self.assertEqual(r["guardrails"]["omitted_conditions"], [{"section": "มาตรา 448", "missing": ["1 ปี"]}])

    def test_complete_answer_makes_one_call(self):
        good = {"answer": "1 ปี หรือ 10 ปี", "citations": [{"section": "มาตรา 448", "quote": self.quote1}]}
        with mock.patch.object(qa_module, "_call_llm", return_value=good) as m:
            r = self.qa.ask(self.q)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(r["status"], "CITATIONS_VERIFIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
