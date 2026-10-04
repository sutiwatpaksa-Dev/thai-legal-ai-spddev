"""
ทดสอบระบบตรวจอ้างอิงของ Q&A โดยจำลองคำตอบของ LLM (ไม่ต้องใช้ Ollama ผลลัพธ์คงที่ทุกครั้ง)
"""

import helpers  # noqa: F401

import unittest
from unittest import mock

from legal_engine import database as db
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA, _verify

S448 = None
S224 = None


def setUpModule():
    global S448, S224
    S448, S224 = db.get_statute("CCC-448"), db.get_statute("CCC-224")


class TestVerify(unittest.TestCase):
    def test_exact_quote_is_verified(self):
        quote = "สิทธิเรียกร้องค่าเสียหายอันเกิดแต่มูลละเมิดนั้น"
        r = _verify({"answer": "ขาดอายุความ", "citations": [{"section": "มาตรา 448", "quote": quote}]}, [S448])
        self.assertEqual(len(r["verified_citations"]), 1)
        self.assertEqual(r["rejected_citations"], [])

    def test_stitched_quote_is_rejected(self):
        """ข้อความที่โมเดลตัดต่อเอง (เคยเกิดจริงกับ ม.448) ต้องไม่ผ่าน"""
        r = _verify({"answer": "", "citations": [{"section": "มาตรา 448",
                     "quote": "ขาดอายุความเมื่อพ้นสิบปีนับแต่วันทำละเมิด"}]}, [S448])
        self.assertEqual(r["verified_citations"], [])
        self.assertIn("ไม่ตรงกับตัวบทจริง", r["rejected_citations"][0]["reason"])

    def test_section_not_provided_is_rejected(self):
        r = _verify({"answer": "", "citations": [{"section": "มาตรา 420", "quote": "สิทธิเรียกร้องค่าเสียหาย"}]}, [S448])
        self.assertIn("ไม่อยู่ในตัวบทที่ค้นพบ", r["rejected_citations"][0]["reason"])

    def test_too_short_quote_is_rejected(self):
        r = _verify({"answer": "", "citations": [{"section": "มาตรา 448", "quote": "นั้น"}]}, [S448])
        self.assertEqual(r["verified_citations"], [])

    def test_whitespace_and_digit_forms_are_normalised(self):
        """ยกข้อความด้วยเลขอารบิกหรือเว้นวรรคต่างจากต้นฉบับได้ (ต้นฉบับใช้เลขไทย)"""
        r = _verify({"answer": "", "citations": [{"section": "ม.224", "quote": "อัตราที่กำหนดตาม มาตรา 7"}]}, [S224])
        self.assertEqual(len(r["verified_citations"]), 1)

    def test_invented_section_in_answer_is_flagged(self):
        quote = "สิทธิเรียกร้องค่าเสียหายอันเกิดแต่มูลละเมิดนั้น"
        r = _verify({"answer": "ตามมาตรา 999", "citations": [{"section": "มาตรา 448", "quote": quote}]}, [S448])
        self.assertEqual(r["unsupported_sections_in_answer"], ["มาตรา 999"])

    def test_cross_referenced_section_is_allowed(self):
        """ม.224 อ้าง 'ตามมาตรา ๗' เอง คำตอบที่กล่าวถึงมาตรา 7 จึงมีที่มา"""
        quote = "อัตราที่กำหนดตามมาตรา ๗"
        r = _verify({"answer": "คิดตามมาตรา 7 บวกร้อยละสอง", "citations": [{"section": "มาตรา 224", "quote": quote}]}, [S224])
        self.assertEqual(r["unsupported_sections_in_answer"], [])

    def test_malformed_citations_are_ignored(self):
        r = _verify({"answer": "x", "citations": ["not a dict", None]}, [S448])
        self.assertEqual(r["verified_citations"], [])


class TestAskStatuses(unittest.TestCase):
    """สถานะของ LegalQA.ask เมื่อจำลองผลจาก LLM"""

    @classmethod
    def setUpClass(cls):
        cls.qa = LegalQA(HybridLegalRetriever(db.list_statutes()))
        cls.q = "อายุความเรียกค่าเสียหายจากการทำละเมิดกี่ปี"

    def ask_with(self, llm_out):
        with mock.patch.object(qa_module, "_call_llm", return_value=llm_out):
            return self.qa.ask(self.q)

    def test_verified(self):
        r = self.ask_with({"answer": "1 ปี หรือ 10 ปี", "insufficient": False, "citations": [
            {"section": "มาตรา 448", "quote": "ขาดอายุความเมื่อพ้นปีหนึ่งนับแต่วันที่ผู้ต้องเสียหายรู้ถึงการละเมิด"}]})
        self.assertEqual(r["status"], "CITATIONS_VERIFIED")
        self.assertEqual(r["citations"][0]["source_page"], 71)

    def test_partial(self):
        r = self.ask_with({"answer": "x", "citations": [
            {"section": "มาตรา 448", "quote": "ขาดอายุความเมื่อพ้นปีหนึ่งนับแต่วันที่ผู้ต้องเสียหายรู้ถึงการละเมิด"},
            {"section": "มาตรา 448", "quote": "ข้อความที่ไม่มีอยู่จริงในตัวบท"}]})
        self.assertEqual(r["status"], "ABSTAIN")
        self.assertEqual(r["citations"], [])

    def test_no_valid_citation_abstains(self):
        r = self.ask_with({"answer": "10 ปี", "citations": [
            {"section": "มาตรา 448", "quote": "ขาดอายุความเมื่อพ้นสิบปีนับแต่วันทำละเมิด"}]})
        self.assertEqual(r["status"], "ABSTAIN")
        self.assertEqual(r["citations"], [])

    def test_insufficient_abstains(self):
        r = self.ask_with({"answer": "ตัวบทไม่พอ", "insufficient": True, "citations": []})
        self.assertEqual(r["status"], "ABSTAIN")

    def test_llm_down_reports_error(self):
        with mock.patch.object(qa_module, "_call_llm", side_effect=ConnectionError("refused at 10.0.0.5:11434")):
            r = self.qa.ask(self.q)
        self.assertEqual((r["status"], r["error_code"]), ("LLM_ERROR", "LLM_UNREACHABLE"))
        self.assertNotIn("10.0.0.5", r["error"])            # ไม่เปิดเผยรายละเอียดภายในให้ผู้ใช้
        self.assertNotIn("debug_error", r)                   # ปิดโหมดดีบักเป็นค่าเริ่มต้น
        self.assertTrue(r["retrieved_statutes"])             # การค้นตัวบทสำเร็จแล้ว ต้องส่งกลับไปแสดง

    def test_out_of_memory_is_classified(self):
        """ข้อความจริงจาก Ollama เมื่อ RAM/VRAM ไม่พอ"""
        err = RuntimeError("llama-server process has terminated: cudaMalloc failed: out of memory "
                           "alloc_tensor_range: failed to allocate CUDA_Host buffer of size 306561024")
        with mock.patch.object(qa_module, "_call_llm", side_effect=err):
            r = self.qa.ask(self.q)
        self.assertEqual(r["error_code"], "LLM_OUT_OF_MEMORY")
        self.assertNotIn("CUDA", r["error"])

    def test_debug_mode_exposes_detail(self):
        with mock.patch.object(qa_module, "DEBUG_ERRORS", True), \
             mock.patch.object(qa_module, "_call_llm", side_effect=ConnectionError("refused")):
            r = self.qa.ask(self.q)
        self.assertIn("refused", r["debug_error"])

    def test_explicit_section_is_always_included(self):
        with mock.patch.object(qa_module, "_call_llm", return_value={"answer": "", "citations": []}) as m:
            r = self.qa.ask("มาตรา 193/30 อายุความกี่ปี")
        self.assertEqual(r["retrieved_statutes"][0]["id"], "CCC-193-30")
        self.assertTrue(m.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
