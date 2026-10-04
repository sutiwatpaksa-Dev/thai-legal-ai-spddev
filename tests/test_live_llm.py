"""
ทดสอบกับโมเดลจริงผ่าน Ollama (ข้ามอัตโนมัติถ้า Ollama ไม่ได้รันหรือไม่มีโมเดล)

คำถามเหล่านี้ตรงกับปุ่มตัวอย่างบนหน้าเว็บ — ถ้าผู้ใช้กดแล้วได้คำตอบผิด ต้องจับได้ที่นี่
ผลจาก LLM อาจแปรผันเล็กน้อย จึงตรวจเฉพาะสิ่งที่ต้องเป็นจริงเสมอ
"""

import helpers

import unittest

from legal_engine import database as db
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA

ANSWERED = ("CITATIONS_VERIFIED", "CITATIONS_PARTIAL")


@unittest.skipUnless(helpers.ollama_ready(), helpers.ollama_skip_reason())
class TestLiveAnswers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa = LegalQA(HybridLegalRetriever(db.list_statutes()))

    def ask(self, q):
        r = self.qa.ask(q)
        self.assertNotEqual(r["status"], "LLM_ERROR", r.get("error"))
        return r

    def assert_cites(self, r, section):
        self.assertIn(r["status"], ANSWERED, r["answer"])
        self.assertIn(section, [c["section"] for c in r["citations"]])

    def test_legal_interest_m7(self):
        r = self.ask("หากไม่ได้กำหนดอัตราดอกเบี้ยไว้โดยนิติกรรมหรือโดยบทกฎหมายอันชัดแจ้ง ให้คิดดอกเบี้ยร้อยละเท่าใดต่อปี?")
        self.assert_cites(r, "มาตรา 7")
        self.assertRegex(r["answer"], r"สาม|3")

    def test_default_interest_m224(self):
        r = self.ask("หนี้เงินผิดนัดให้คิดดอกเบี้ยร้อยละเท่าใดต่อปี และสามารถคิดดอกเบี้ยซ้อนในระหว่างผิดนัดได้หรือไม่?")
        self.assert_cites(r, "มาตรา 224")

    def test_loan_m653(self):
        r = self.ask("การกู้ยืมเงินมีจำนวนเกินกว่าเท่าใดที่ต้องมีหลักฐานแห่งการกู้ยืมเป็นหนังสือจึงจะฟ้องร้องบังคับคดีได้?")
        self.assert_cites(r, "มาตรา 653")
        self.assertRegex(r["answer"], r"สองพัน|2,?000")

    def test_employer_m425(self):
        r = self.ask("ลูกจ้างขับรถส่งของชนผู้อื่นเสียหายในทางการที่จ้าง นายจ้างต้องร่วมรับผิดกับลูกจ้างหรือไม่?")
        self.assert_cites(r, "มาตรา 425")

    def test_lease_m566(self):
        r = self.ask("การบอกเลิกสัญญาเช่าทรัพย์สินที่มิได้กำหนดเวลาไว้ คู่สัญญาต้องบอกกล่าวล่วงหน้าอย่างไร?")
        self.assert_cites(r, "มาตรา 566")

    def test_tort_limitation_never_wrong(self):
        """
        เคยตอบผิดว่า '10 ปี' แต่ได้สถานะ VERIFIED — ห้ามเกิดอีก:
        VERIFIED ต้องระบุ 1 ปีด้วย, ถ้าตกหล่นต้องเป็น PARTIAL พร้อมคำเตือน, หรือไม่ตอบ (ABSTAIN)
        """
        r = self.ask("อายุความเรียกค่าเสียหายจากการทำละเมิดกี่ปี")
        if r["status"] == "CITATIONS_VERIFIED":
            self.assertRegex(r["answer"], r"ปีหนึ่ง|1 ปี|หนึ่งปี", r["answer"])
        elif r["status"] == "CITATIONS_PARTIAL" and not r["guardrails"].get("rejected_citations"):
            self.assertTrue(r["guardrails"]["omitted_conditions"], r["answer"])

    def test_out_of_scope_abstains(self):
        r = self.ask("การเดินทางไปดาวอังคารด้วยยานอวกาศโดยไม่ขออนุญาตองค์การอวกาศสากล ผิดกฎหมายแพ่งหรือไม่?")
        self.assertEqual(r["status"], "ABSTAIN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
