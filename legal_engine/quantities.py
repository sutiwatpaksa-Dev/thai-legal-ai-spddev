"""
สกัดปริมาณทางกฎหมาย (ระยะเวลา จำนวนเงิน อัตราร้อยละ) จากข้อความภาษาไทย

ใช้ตรวจว่าคำตอบของ AI ระบุเงื่อนไขครบตามตัวบทหรือไม่ เช่น ม.448 กำหนดทั้ง "ปีหนึ่ง" และ "สิบปี"
ถ้าคำตอบพูดถึงหน่วย "ปี" แต่มีแค่ 10 ปี แปลว่าตกหล่นเงื่อนไข 1 ปี
"""

import re
from typing import Set, Tuple

_DIGITS = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4,
           "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9}
_SCALES = {"สิบ": 10, "ร้อย": 100, "พัน": 1000, "หมื่น": 10000, "แสน": 100000, "ล้าน": 1000000}
_WORD = "|".join(sorted(list(_DIGITS) + list(_SCALES), key=len, reverse=True))
_NUM = rf"(?:[0-9๐-๙][0-9๐-๙,]*|(?:{_WORD})+)"
_UNITS = ["ปี", "เดือน", "สัปดาห์", "วัน", "บาท"]
_UNIT = "|".join(_UNITS)

# "สิบปี", "2,000 บาท", "๓ เดือน"
_NUM_UNIT = re.compile(rf"({_NUM})\s*({_UNIT})")
# "ปีหนึ่ง", "เดือนหนึ่ง" (สำนวนกฎหมาย = 1 หน่วย)
_UNIT_ONE = re.compile(rf"({_UNIT})หนึ่ง")
# "ร้อยละสาม", "ร้อยละ 5"
_PERCENT = re.compile(rf"ร้อยละ\s*({_NUM})")

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

Quantity = Tuple[int, str]


def thai_number(text: str) -> int:
    """'สองพัน' -> 2000, 'สิบห้า' -> 15, 'ยี่สิบเอ็ด' -> 21, '๓' -> 3, '2,000' -> 2000"""
    t = text.translate(_THAI_DIGITS).replace(",", "")
    if t.isdigit():
        return int(t)
    total, current = 0, 0
    for tok in re.findall(_WORD, text):
        if tok in _DIGITS:
            current = _DIGITS[tok]
        else:
            scale = _SCALES[tok]
            if scale == 1000000:
                total = (total + (current or 1)) * scale
            else:
                total += (current or 1) * scale
            current = 0
    return total + current


def extract(text: str) -> Set[Quantity]:
    found: Set[Quantity] = set()
    for num, unit in _NUM_UNIT.findall(text):
        # "ปีหนึ่งนับแต่" — คำว่า "หนึ่ง" ที่ตามหลังหน่วยไม่ใช่ตัวเลขของหน่วยถัดไป
        value = thai_number(num)
        if value:
            found.add((value, unit))
    for unit in _UNIT_ONE.findall(text):
        found.add((1, unit))
    for num in _PERCENT.findall(text):
        value = thai_number(num)
        if value:
            found.add((value, "ร้อยละ"))
    return found


def omitted(answer: str, source: str) -> Set[Quantity]:
    """
    ปริมาณในตัวบทที่คำตอบไม่ได้กล่าวถึง — นับเฉพาะหน่วยที่คำตอบพูดถึงอยู่แล้ว
    (ถ้าคำตอบไม่ได้พูดเรื่องเงินเลย จะไม่บังคับให้ระบุจำนวนเงิน)
    """
    in_answer = extract(answer)
    units = {u for _, u in in_answer}
    return {q for q in extract(source) if q[1] in units and q not in in_answer}


def describe(q: Quantity) -> str:
    value, unit = q
    return f"ร้อยละ {value}" if unit == "ร้อยละ" else f"{value:,} {unit}"
