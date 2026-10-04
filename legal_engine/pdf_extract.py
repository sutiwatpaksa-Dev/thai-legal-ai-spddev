"""
Thai PDF Text Extraction (สกัดข้อความภาษาไทยจาก PDF แบบตัดอักขระซ้อนทับ)

PDF ประมวลกฎหมายฉบับนี้มีชั้นอักขระซ้ำ: พยัญชนะ+สระบน/วรรณยุกต์ถูกวาดซ้ำ
เป็นกล่องเตี้ยๆ ที่ลอยสูงกว่าตัวจริงเล็กน้อย ทำให้ข้อความดิบออกมาเป็น
"สิทสิ ธิแธิห่ง" แทน "สิทธิแห่ง" และมีช่องว่างปลอมที่วางย้อนหลังทับอักขระก่อนหน้า
บางส่วนของชั้นซ้ำถูกเรียงไว้ท้ายหน้า จึงต้องเทียบตำแหน่งกับอักขระทั้งหน้า
ไม่ใช่เฉพาะอักขระที่อยู่ติดกัน
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import List

import pypdfium2 as pdfium

_X_TOLERANCE = 6.0      # ตัวซ้ำเลื่อนแนวนอนจากตัวจริงได้ถึง ~4pt
_RAISED_MIN = 2.0       # ตัวซ้ำอยู่สูงกว่าตัวจริงอย่างน้อยเท่านี้ (pt)
_RAISED_MAX = 10.0      # แต่ไม่สูงถึงระยะบรรทัดก่อนหน้า (~14pt)
_SHORT_RATIO = 0.7      # ตัวซ้ำที่จมต่ำต้องเตี้ยกว่าตัวจริงชัดเจน (~3pt เทียบ ~6pt)
_OVERLAP_SLACK = 0.5    # ยอมให้ขอบกล่องตัวซ้ำกับตัวจริงซ้อนกันได้เล็กน้อย
_ENCLOSE_X_TOLERANCE = 1.5  # ตัวซ้ำแบบกล่องครอบต้องอยู่ตำแหน่ง x เกือบตรงกัน
_INVISIBLE_WIDTH = 0.5 # อักขระจริงทุกตัว (รวมตัวซ้ำ) กว้างอย่างน้อย ~1pt
_MIN_SPACE_GAP = 2.0    # ระยะห่างขั้นต่ำที่ถือว่าเป็นการเว้นวรรคจริง

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def thai_to_arabic(text: str) -> str:
    return text.translate(_THAI_DIGITS)


@dataclass
class Line:
    page: int       # เลขหน้า (เริ่มที่ 1)
    x0: float       # ตำแหน่งซ้ายของอักขระแรกที่ไม่ใช่ช่องว่าง (ใช้ดูการย่อหน้า)
    text: str


def _is_copy_of(copy, orig) -> bool:
    _, lc, bc, _rc, tc = copy
    _, lo, bo, _ro, to = orig
    if abs(lc - lo) >= _X_TOLERANCE:
        return False
    shift = bc - bo
    # ตัวซ้ำลอยอยู่เหนือกล่องตัวจริงทั้งกล่อง (สระบน/วรรณยุกต์) - บรรทัดห่างกัน ~14pt
    # ต้องไม่ซ้อนทับแนวตั้ง: กล่องสูงผิดปกติของ "ผู้" ไม่ทำให้ "ซื้" ถูกตัดวรรณยุกต์
    if _RAISED_MIN <= shift <= _RAISED_MAX and bc >= to - _OVERLAP_SLACK:
        return True
    # ตัวซ้ำจมอยู่ใต้กล่องตัวจริง (สระล่าง) - แยกจากบรรทัดถัดไปด้วยความสูงกล่องที่เตี้ยกว่ามาก
    if (_RAISED_MIN <= -shift <= _RAISED_MAX and tc <= bo + _OVERLAP_SLACK
            and (tc - bc) < (to - bo) * _SHORT_RATIO):
        return True
    # ตัวซ้ำกล่องสูงที่ครอบตัวจริงทั้งบนและล่าง ณ ตำแหน่ง x เดียวกัน
    if abs(lc - lo) < _ENCLOSE_X_TOLERANCE and bc < bo - _OVERLAP_SLACK and tc > to + _OVERLAP_SLACK:
        return True
    return False


def _find_duplicates(chars) -> set:
    """
    คืน index ของอักขระที่เป็นชั้นซ้ำ: ตัวซ้ำจะมาหลังตัวจริงในลำดับข้อความเสมอ
    บางตัวถูกเรียงไว้ไกลถึงท้ายหน้า จึงเทียบกับอักขระตัวเดียวกันที่มาก่อนทั้งหน้า
    """
    by_char = defaultdict(list)
    for idx, (ch, *_box) in enumerate(chars):
        if ch.strip():
            by_char[ch].append(idx)

    dups = set()
    for idxs in by_char.values():
        for pos, i in enumerate(idxs):
            if any(j not in dups and _is_copy_of(chars[i], chars[j]) for j in idxs[:pos]):
                dups.add(i)
    return dups


def extract_page_lines(page: "pdfium.PdfPage", page_no: int) -> List[Line]:
    tp = page.get_textpage()
    chars = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        chars.append((ch, *tp.get_charbox(i)))

    dups = _find_duplicates(chars)

    lines: List[Line] = []
    glyphs: List[tuple] = []  # (char, left, right) ของบรรทัดปัจจุบัน ไม่รวมช่องว่าง
    space_before: List[bool] = []

    def flush():
        nonlocal glyphs, space_before
        if glyphs:
            out = []
            for k, (ch, left, _right) in enumerate(glyphs):
                # เว้นวรรคจริงมีระยะห่างที่มองเห็น (~4-6pt); ช่องว่างปลอมห่าง ~1pt หรือซ้อนทับ
                if k and space_before[k] and left - glyphs[k - 1][2] >= _MIN_SPACE_GAP:
                    out.append(" ")
                out.append(ch)
            lines.append(Line(page_no, glyphs[0][1], "".join(out)))
        glyphs, space_before = [], []

    pending_space = False
    for idx, (ch, left, bottom, right, _top) in enumerate(chars):
        if ch == "\r":
            continue
        if ch == "\n":
            flush()
            pending_space = False
            continue
        if idx in dups:
            continue
        if not ch.strip():
            # ช่องว่างที่วางย้อนหลังทับอักขระก่อนหน้า (เช่นหลัง "ำ" ใน "สำ คัญ") เป็นของปลอม
            if not (glyphs and left < glyphs[-1][2] - 0.5):
                pending_space = True
            continue
        # glyph ล่องหนท้ายหน้า (กว้าง ~0.2pt) เป็นสำเนาของคำท้ายหน้า ไม่ใช่ข้อความจริง
        if right - left < _INVISIBLE_WIDTH:
            continue
        glyphs.append((ch, left, right))
        space_before.append(pending_space)
        pending_space = False
    flush()
    return lines


def extract_pdf_lines(path: str) -> List[Line]:
    pdf = pdfium.PdfDocument(path)
    try:
        out: List[Line] = []
        for n, page in enumerate(pdf, start=1):
            out.extend(extract_page_lines(page, n))
        return out
    finally:
        pdf.close()
