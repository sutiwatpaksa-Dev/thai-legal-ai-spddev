"""
นำเข้าประมวลกฎหมายแพ่งและพาณิชย์จาก code_lawyer.pdf ลงฐานข้อมูล SQLite

หลักการ (ดู AGENTS.md):
- เนื้อหาแต่ละมาตราเป็นข้อความจริงจาก PDF (ตัวเลขไทยคงไว้ตามต้นฉบับ) ไม่สร้างข้อมูลเอง
- มาตราเริ่มเฉพาะบรรทัดที่ขึ้นต้นด้วย "มาตรา N" และย่อหน้าเข้าไป (x ≈ 180)
  การอ้างถึงมาตราอื่นที่ตัดบรรทัดมาอยู่ต้นบรรทัดจะอยู่ชิดขอบซ้าย (x ≈ 108) จึงไม่ถูกนับ
- เลขมาตราต้องเรียงขึ้นตลอด: ใช้ Longest Increasing Subsequence ตัดหัวมาตราที่ผิดลำดับ
- ตัดส่วนพระราชกฤษฎีกาก่อนหน้า และพระราชบัญญัติแก้ไขเพิ่มเติมท้ายเล่ม
- บรรพ / ลักษณะ / หมวด / ส่วน อ่านจากหัวเรื่องจริงใน PDF

ใช้งาน:  .venv\\Scripts\\python ingest_pdf.py [--dry-run]
"""

import argparse
import bisect
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from legal_engine import database as db
from legal_engine.pdf_extract import Line, extract_pdf_lines, thai_to_arabic

PDF_PATH = "code_lawyer.pdf"
SOURCE = "code_lawyer.pdf"
CATEGORY = "ประมวลกฎหมายแพ่งและพาณิชย์"
ID_PREFIX = "CCC"

THAI_NUM = "[๐-๙0-9]+"
SUFFIXES = ["ทวิ", "ตรี", "จัตวา", "เบญจ", "ฉ", "สัตต", "อัฏฐ", "นว"]
SUFFIX_IDS = {"ทวิ": "bis", "ตรี": "ter", "จัตวา": "quater", "เบญจ": "quinquies",
              "ฉ": "sexies", "สัตต": "septies", "อัฏฐ": "octies", "นว": "novies"}

SECTION_RE = re.compile(
    rf"^มาตรา\s*(?P<num>{THAI_NUM})(?:\s*/\s*(?P<sub>{THAI_NUM}))?"
    rf"\s*(?P<suf>{'|'.join(SUFFIXES)})?(?=\s|\(|$)(?P<rest>.*)$"
)
HEADING_RE = re.compile(rf"^(?P<level>บรรพ|ลักษณะ|หมวด|ส่วนที่|ส่วน)\s*(?P<num>{THAI_NUM})\s*$")
LEVELS = ["บรรพ", "ลักษณะ", "หมวด", "ส่วน"]

BODY_START = "ข้อความเบื้องต้น"
BODY_END_RE = re.compile(r"^พระราชบัญญัติแก้ไขเพิ่มเติมประมวลกฎหมายแพ่งและพา")

SECTION_X = (170.0, 195.0)   # ระยะย่อหน้าของหัวมาตรา
PARAGRAPH_X = 170.0          # บรรทัดที่ย่อหน้าเข้าไปเท่านี้ขึ้นไป = ขึ้นวรรคใหม่
CENTERED_X = 200.0           # ชื่อหัวเรื่องจัดกึ่งกลาง


@dataclass
class Section:
    key: Tuple[int, int, int]
    label: str
    page: int
    book: str
    title: str
    paragraphs: List[str] = field(default_factory=list)

    @property
    def content(self) -> str:
        return "\n".join(p.strip() for p in self.paragraphs if p.strip())


def parse_key(m: re.Match) -> Tuple[Tuple[int, int, int], str]:
    num = int(thai_to_arabic(m.group("num")))
    sub = int(thai_to_arabic(m.group("sub"))) if m.group("sub") else 0
    suf = m.group("suf") or ""
    label = f"มาตรา {num}" + (f"/{sub}" if sub else "") + (f" {suf}" if suf else "")
    return (num, sub, SUFFIXES.index(suf) + 1 if suf else 0), label


def section_id(key: Tuple[int, int, int]) -> str:
    num, sub, suf = key
    out = f"{ID_PREFIX}-{num}"
    if sub:
        out += f"-{sub}"
    if suf:
        out += f"-{SUFFIX_IDS[SUFFIXES[suf - 1]]}"
    return out


def is_noise(line: Line, page_lines: List[Line], idx: int) -> bool:
    t = line.text
    if re.fullmatch(r"\[\d+\]|\.+|-?\s*\d+\s*-?", t):
        return True  # เครื่องหมายเชิงอรรถ จุด หรือเลขหน้า
    # เศษอักขระท้ายหน้า เช่น "นั้", "นี้ นั้": คำสั้นล้วนในไม่กี่บรรทัดสุดท้ายของหน้า
    tail = idx >= len(page_lines) - 4
    return tail and len(t) <= 12 and all(len(tok) <= 3 for tok in t.split())


def longest_increasing(keys: List[Tuple]) -> set:
    """index ของ Longest Strictly Increasing Subsequence"""
    tails, tails_idx, prev = [], [], [-1] * len(keys)
    for i, k in enumerate(keys):
        pos = bisect.bisect_left(tails, k)
        if pos == len(tails):
            tails.append(k); tails_idx.append(i)
        else:
            tails[pos] = k; tails_idx[pos] = i
        prev[i] = tails_idx[pos - 1] if pos else -1
    keep, i = set(), tails_idx[-1] if tails_idx else -1
    while i != -1:
        keep.add(i); i = prev[i]
    return keep


def body_lines(lines: List[Line]) -> List[Line]:
    """เฉพาะตัวประมวลกฎหมาย: ตั้งแต่ 'ข้อความเบื้องต้น' ถึงก่อน พ.ร.บ. แก้ไขเพิ่มเติมฉบับแรก"""
    start = next(i for i, l in enumerate(lines) if l.text == BODY_START)
    end = next((i for i, l in enumerate(lines) if i > start and BODY_END_RE.match(l.text)), len(lines))
    by_page: Dict[int, List[Line]] = {}
    for l in lines:
        by_page.setdefault(l.page, []).append(l)
    out = []
    for i in range(start + 1, end):
        l = lines[i]
        page_lines = by_page[l.page]
        if not is_noise(l, page_lines, page_lines.index(l)):
            out.append(l)
    return out


def parse_sections(lines: List[Line]) -> Tuple[List[Section], List[Line]]:
    # 1) หาหัวมาตราที่เป็นไปได้ แล้วคัดเฉพาะชุดที่เลขเรียงขึ้นยาวที่สุด
    cands = []
    for i, l in enumerate(lines):
        m = SECTION_RE.match(l.text)
        if m and SECTION_X[0] <= l.x0 <= SECTION_X[1]:
            cands.append((i, *parse_key(m), m))
    keep = longest_increasing([c[1] for c in cands])
    headers = {cands[k][0]: cands[k] for k in keep}
    rejected = [lines[cands[k][0]] for k in range(len(cands)) if k not in keep]

    # 2) เดินทีละบรรทัด สร้างมาตราพร้อมหัวเรื่อง บรรพ/ลักษณะ/หมวด/ส่วน
    sections: List[Section] = []
    heading: Dict[str, str] = {}
    pending_level: Optional[str] = None
    pending_has_name = False
    cur: Optional[Section] = None

    for i, l in enumerate(lines):
        hm = HEADING_RE.match(l.text)
        if hm:
            level = "ส่วน" if hm.group("level").startswith("ส่วน") else hm.group("level")
            heading[level] = f"{level} {thai_to_arabic(hm.group('num'))}"
            for lower in LEVELS[LEVELS.index(level) + 1:]:
                heading.pop(lower, None)
            pending_level, pending_has_name = level, False
            continue
        if pending_level and i not in headers and l.x0 >= CENTERED_X:
            # ชื่อหัวเรื่อง (จัดกึ่งกลาง) - บรรทัดที่สองขึ้นไปเป็นส่วนต่อของชื่อเดิม
            heading[pending_level] += l.text if pending_has_name else f" {l.text}"
            pending_has_name = True
            continue
        pending_level = None

        if i in headers:
            _, key, label, m = headers[i]
            cur = Section(
                key=key, label=label, page=l.page,
                book=heading.get("บรรพ", ""),
                title=" › ".join(heading[k] for k in LEVELS[1:] if k in heading),
                paragraphs=[m.group("rest").strip()],
            )
            sections.append(cur)
        elif cur is not None:
            if l.x0 >= PARAGRAPH_X and l.x0 < CENTERED_X:
                cur.paragraphs.append(l.text)        # วรรคใหม่
            else:
                cur.paragraphs[-1] += l.text         # ต่อบรรทัด (ภาษาไทยไม่เว้นวรรคระหว่างคำ)
    return sections, rejected


def arabic_to_thai(text: str) -> str:
    return text.translate(str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙"))


RANGE_REPEAL_RE = re.compile(rf"^ถึง\s*มาตรา\s*(?P<end>{THAI_NUM})\s*\(?\s*ยกเลิก\s*\)?$")


def to_records(sections: List[Section]) -> List[dict]:
    def record(key, label, s, content, repealed):
        return {
            "id": section_id(key),
            "category": CATEGORY,
            "book": s.book or BODY_START,   # มาตรา 1-3 อยู่ใต้ "ข้อความเบื้องต้น" ก่อนบรรพ 1
            "title": s.title or s.book or BODY_START,
            "section": label,
            "content": content,
            "keywords": [],
            "elements": [],
            "status": "repealed" if repealed else "active",
            "source": SOURCE,
            "source_page": s.page,
        }

    records = []
    for s in sections:
        content = s.content
        rm = RANGE_REPEAL_RE.match(content)
        if rm and s.key[1:] == (0, 0):
            # ต้นฉบับยกเลิกเป็นช่วง เช่น "มาตรา ๑๒๗๔ ถึง มาตรา ๑๒๙๗ (ยกเลิก)"
            # ทุกมาตราในช่วงเก็บบรรทัดต้นฉบับนั้นเป็นเนื้อหา ไม่แต่งข้อความเพิ่ม
            original = f"มาตรา {arabic_to_thai(str(s.key[0]))} {content}"
            for n in range(s.key[0], int(thai_to_arabic(rm.group("end"))) + 1):
                records.append(record((n, 0, 0), f"มาตรา {n}", s, original, True))
            continue
        repealed = bool(re.fullmatch(r"\(?\s*ยกเลิก\s*\)?", content))
        records.append(record(s.key, s.label, s, content, repealed))
    return records


def merge_curated(records: List[dict]) -> int:
    """
    ตัวบทที่เขียนด้วยมือใน knowledge_base.py: คง keywords/elements ไว้
    แต่เนื้อหาและหัวเรื่องใช้จาก PDF (หัวเรื่องใน PDF ละเอียดกว่า)
    """
    curated = {s["id"]: s for s in db._curated_statutes() if s["category"] == CATEGORY}
    merged = 0
    for r in records:
        c = curated.get(r["id"])
        if c:
            r["keywords"], r["elements"] = c.get("keywords", []), c.get("elements", [])
            merged += 1
    return merged


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ไม่เขียนฐานข้อมูล แค่รายงานผล")
    ap.add_argument("--dump", help="บันทึกผลเป็น JSON เพื่อตรวจสอบ")
    args = ap.parse_args()

    lines = extract_pdf_lines(PDF_PATH)
    sections, rejected = parse_sections(body_lines(lines))
    records = to_records(sections)
    merged = merge_curated(records)

    print(f"Sections parsed: {len(records)} "
          f"(repealed {sum(r['status'] == 'repealed' for r in records)}, curated merged {merged})")
    print(f"Header-like lines rejected as out of order: {len(rejected)}")
    for l in rejected[:10]:
        print(f"  p{l.page}: {l.text[:70]}")

    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)

    if args.dry_run:
        return
    db.init_db()
    with db.get_conn() as conn:
        # แทนที่ข้อมูลประมวลฯ ทั้งชุดในทรานแซกชันเดียว (ตัวบทหมวดอื่นไม่ถูกแตะ)
        conn.execute("DELETE FROM statutes WHERE category = ?", (CATEGORY,))
        db.upsert_statutes(conn, records)
    print(f"Wrote {len(records)} sections to {db.DB_PATH}")


if __name__ == "__main__":
    main()
