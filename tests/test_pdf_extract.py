"""
ทดสอบการตัดอักขระซ้ำของ PDF ด้วยตำแหน่งกล่องอักขระจริงที่วัดได้จาก code_lawyer.pdf
(char, left, bottom, right, top)
"""

import helpers  # noqa: F401

import os
import unittest

from legal_engine.pdf_extract import _is_copy_of, extract_page_lines

PDF = os.path.join(helpers.ROOT, "code_lawyer.pdf")


class TestCopyDetection(unittest.TestCase):
    def test_raised_copy(self):
        """'รับรั' หน้า 6: ร ซ้ำลอยเหนือตัวจริง"""
        self.assertTrue(_is_copy_of(("ร", 199.7, 723.4, 201.9, 725.8), ("ร", 198.3, 716.6, 200.5, 722.6)))

    def test_raised_copy_shifted_4pt(self):
        """'อย่าย่' หน้า 6: ตัวซ้ำเลื่อนแนวนอน ~4pt"""
        self.assertTrue(_is_copy_of(("ย", 236.5, 681.4, 236.9, 683.7), ("ย", 232.5, 674.7, 234.9, 680.6)))

    def test_lowered_short_copy(self):
        """'เหใตุ' หน้า 2: ตัวซ้ำของสระล่างจมใต้ตัวจริงและเตี้ยกว่า"""
        self.assertTrue(_is_copy_of(("ต", 384.9, 544.9, 385.9, 547.9), ("ต", 381.9, 548.7, 384.4, 554.6)))

    def test_enclosing_copy(self):
        """'ลูสู้ กหนี้' มาตรา 236: ตัวซ้ำกล่องสูงครอบตัวจริงที่ x เดียวกัน"""
        self.assertTrue(_is_copy_of(("ส", 298.9, 350.6, 300.4, 363.8), ("ส", 298.0, 354.3, 299.6, 361.0)))

    def test_tall_box_is_not_an_original_for_next_word(self):
        """'ผู้ซื้อ': กล่องสูงผิดปกติของ ้ ใน 'ผู้' ต้องไม่ทำให้ ้ ใน 'ซื้' ถูกตัด"""
        self.assertFalse(_is_copy_of(("้", 413.2, 616.9, 415.0, 623.3), ("้", 407.5, 613.1, 409.3, 626.3)))

    def test_same_char_on_next_line_is_kept(self):
        self.assertFalse(_is_copy_of(("ก", 101.0, 686.0, 106.0, 692.0), ("ก", 100.0, 700.0, 105.0, 706.0)))

    def test_same_char_on_previous_line_is_kept(self):
        self.assertFalse(_is_copy_of(("ก", 101.0, 714.0, 106.0, 720.0), ("ก", 100.0, 700.0, 105.0, 706.0)))

    def test_far_apart_on_same_line_is_kept(self):
        self.assertFalse(_is_copy_of(("ร", 260.0, 723.4, 262.0, 725.8), ("ร", 198.3, 716.6, 200.5, 722.6)))


@unittest.skipUnless(os.path.exists(PDF), "ไม่มี code_lawyer.pdf")
class TestRealPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(PDF)
        cls.page2 = "\n".join(l.text for l in extract_page_lines(pdf[1], 2))
        cls.page6 = "\n".join(l.text for l in extract_page_lines(pdf[5], 6))
        cls.page2_lines = extract_page_lines(pdf[1], 2)
        pdf.close()

    def test_page2_clean_text(self):
        for good in ["มาตรา ๕ ในการใช้สิทธิแห่งตน", "กระทำโดยสุจริต", "เหตุใด ๆ", "จะให้ผลพิบัติ", "ร้อยละสามต่อปี"]:
            self.assertIn(good, self.page2)
        for bad in ["สิทสิ", "สุจสุ", "เหใตุ", "ร้อร้"]:
            self.assertNotIn(bad, self.page2)

    def test_page6_clean_text(self):
        for good in ["รับการให้โดยเสน่หา", "อย่างหนึ่งอย่างใด", "อสังหาริมทรัพย์", "การร้องขอ"]:
            self.assertIn(good, self.page6)
        for bad in ["รับรั", "อย่าย่", "สังสั", "ร้อร้"]:
            self.assertNotIn(bad, self.page6)

    def test_section_headers_are_indented(self):
        """หัวมาตราย่อหน้าที่ x≈180 ซึ่ง ingest_pdf.py ใช้แยกจากการอ้างถึงมาตราที่ตัดบรรทัด"""
        headers = [l for l in self.page2_lines if l.text.startswith("มาตรา ")]
        self.assertTrue(headers)
        for l in headers:
            self.assertTrue(170 <= l.x0 <= 195, (l.x0, l.text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
