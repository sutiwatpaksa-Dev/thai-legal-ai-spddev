"""ทดสอบความครบถ้วนและความถูกต้องของคลังตัวบท (ข้อมูลจริงจาก code_lawyer.pdf)"""

import helpers  # noqa: F401  (ต้องมาก่อน legal_engine)

import re
import subprocess
import sys
import unittest

from legal_engine import database as db

CCC = "ประมวลกฎหมายแพ่งและพาณิชย์"


class TestSectionCompleteness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = db.list_statutes(category=CCC)
        cls.by_section = {r["section"]: r for r in cls.rows}

    def test_verify_script_passes(self):
        """tools/verify_sections.py ต้องผ่านทุกข้อ (ขาด/ซ้ำ/ลำดับ/ว่าง/รวม/เพี้ยน)"""
        proc = subprocess.run([sys.executable, "tools/verify_sections.py"], cwd=helpers.ROOT,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_main_section_1_to_1755(self):
        mains = {int(re.match(r"มาตรา (\d+)", s).group(1)) for s in self.by_section}
        self.assertEqual(set(range(1, 1756)) - mains, set())

    def test_counts(self):
        self.assertEqual(len(self.rows), 1872)
        self.assertEqual(sum(r["status"] == "repealed" for r in self.rows), 37)
        self.assertEqual(sum("/" in r["section"] for r in self.rows), 116)

    def test_ids_are_url_safe_and_unique(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^CCC-[0-9]+(-[0-9]+)?(-[a-z]+)?$")

    def test_every_row_has_source_page(self):
        for r in self.rows:
            self.assertEqual(r["source"], "code_lawyer.pdf", r["section"])
            self.assertTrue(1 <= r["source_page"] <= 306, r["section"])

    def test_no_placeholder_metadata(self):
        """ห้ามมี keywords/elements แบบ placeholder ที่สคริปต์เก่าเคยสร้าง"""
        for r in self.rows:
            self.assertFalse(any(e.startswith("บทบัญญัติตาม") for e in r["elements"]), r["section"])
            self.assertNotIn(r["section"], r["keywords"])


class TestVerbatimText(unittest.TestCase):
    """ตรวจข้อความจริงของมาตราสำคัญ (คัดลอกจาก PDF ไม่ใช่เขียนเอง)"""

    def get(self, sid):
        s = db.get_statute(sid)
        self.assertIsNotNone(s, sid)
        return s

    def test_420(self):
        s = self.get("CCC-420")
        self.assertTrue(s["content"].startswith("ผู้ใดจงใจหรือประมาทเลินเล่อ ทำต่อบุคคลอื่นโดยผิดกฎหมาย"))
        self.assertIn("ท่านว่าผู้นั้นทำละเมิดจำต้องใช้ค่าสินไหมทดแทนเพื่อการนั้น", s["content"])
        self.assertEqual(s["book"], "บรรพ 2 หนี้")
        self.assertIn("ลักษณะ 5 ละเมิด", s["title"])

    def test_448_both_limitation_periods(self):
        c = self.get("CCC-448")["content"]
        self.assertIn("ขาดอายุความเมื่อพ้นปีหนึ่งนับแต่วันที่ผู้ต้องเสียหายรู้ถึงการละเมิด", c)
        self.assertIn("หรือเมื่อพ้นสิบปีนับแต่วันทำละเมิด", c)

    def test_653(self):
        c = self.get("CCC-653")["content"]
        self.assertIn("การกู้ยืมเงินกว่าสองพันบาทขึ้นไปนั้น", c)
        self.assertIn("จะฟ้องร้องให้บังคับคดีหาได้ไม่", c)

    def test_thai_digits_kept_as_in_pdf(self):
        self.assertIn("ตามมาตรา ๗", self.get("CCC-224")["content"])

    def test_previously_garbled_sections_are_clean(self):
        self.assertIn("ลูกหนี้เดิม", self.get("CCC-236")["content"])     # เคยเป็น "ลูสู้ กหนี้"
        self.assertIn("ผู้ซื้อผู้ขาย", self.get("CCC-457")["content"])   # เคยเป็น "ผู้ซือ"
        self.assertIn("สุจริต", self.get("CCC-5")["content"])             # เคยเป็น "สุจสุ ริต"

    def test_slash_and_suffix_sections(self):
        self.assertEqual(self.get("CCC-193-1")["section"], "มาตรา 193/1")
        bis = self.get("CCC-1096-bis")
        self.assertEqual((bis["section"], bis["status"]), ("มาตรา 1096 ทวิ", "repealed"))

    def test_range_repeal_1274_to_1297(self):
        for n in (1274, 1280, 1297):
            s = self.get(f"CCC-{n}")
            self.assertEqual(s["status"], "repealed")
            self.assertEqual(s["content"], "มาตรา ๑๒๗๔ ถึง มาตรา ๑๒๙๗ (ยกเลิก)")

    def test_preliminary_sections_have_book(self):
        self.assertEqual(self.get("CCC-1")["book"], "ข้อความเบื้องต้น")

    def test_cross_reference_did_not_split_section(self):
        """'ตามมาตรา ๓๕' ในมาตรา 30 ต้องเป็นส่วนหนึ่งของเนื้อหา ไม่ใช่หัวมาตราใหม่"""
        found = [r for r in db.list_statutes(category=CCC) if "ตามมาตรา ๓๕" in r["content"]]
        self.assertTrue(found)
        self.assertNotIn("มาตรา 35", [r["section"] for r in found])


if __name__ == "__main__":
    unittest.main(verbosity=2)
