"""
ตรวจความครบถ้วนของเลขมาตราประมวลกฎหมายแพ่งและพาณิชย์ในฐานข้อมูล

ตรวจ:
- เลขมาตราหลักขาดหาย (ช่องว่างในลำดับ 1..N)
- มาตราย่อย /1, /2, ... ขาดหายภายในชุด
- เลขซ้ำ, ลำดับผิด, เนื้อหาว่าง
- เนื้อหามีหัว "มาตรา N" ต้นวรรค ซึ่งแปลว่าสองมาตราอาจถูกรวมกัน
- ข้อความภาษาไทยผิดเพี้ยน (สัดส่วนคำนอกพจนานุกรมสูง)

ใช้งาน:
  .venv\\Scripts\\python tools\\verify_sections.py            # อ่านจากฐานข้อมูล
  .venv\\Scripts\\python tools\\verify_sections.py --json f   # อ่านจากไฟล์ที่ ingest_pdf.py --dump สร้าง
คืนค่า exit code 1 หากพบปัญหาที่ต้องแก้
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CATEGORY = "ประมวลกฎหมายแพ่งและพาณิชย์"
SUFFIXES = ["ทวิ", "ตรี", "จัตวา", "เบญจ", "ฉ", "สัตต", "อัฏฐ", "นว"]
LABEL_RE = re.compile(rf"^มาตรา (\d+)(?:/(\d+))?(?: ({'|'.join(SUFFIXES)}))?$")
OOV_LIMIT = 0.08   # ถ้าคำนอกพจนานุกรมเกิน 8% ของมาตรา ถือว่าข้อความน่าจะเพี้ยน


def load(json_path):
    if json_path:
        with open(json_path, encoding="utf-8") as f:
            return [r for r in json.load(f) if r["category"] == CATEGORY]
    from legal_engine import database as db
    return db.list_statutes(category=CATEGORY)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--no-text-check", action="store_true", help="ข้ามการตรวจคำนอกพจนานุกรม")
    args = ap.parse_args()

    rows = load(args.json)
    problems = defaultdict(list)

    keys = []
    for r in rows:
        m = LABEL_RE.match(r["section"])
        if not m:
            problems["bad label"].append(r["section"])
            continue
        suf = SUFFIXES.index(m.group(3)) + 1 if m.group(3) else 0
        keys.append(((int(m.group(1)), int(m.group(2) or 0), suf), r))

    # ซ้ำ / ลำดับ
    counts = Counter(k for k, _ in keys)
    problems["duplicate"] = [r["section"] for k, r in keys if counts[k] > 1]
    problems["out of order"] = [keys[i][1]["section"] for i in range(1, len(keys)) if keys[i][0] <= keys[i - 1][0]]

    # เลขหลักขาด
    mains = sorted({k[0] for k, _ in keys})
    present = set(mains)
    problems["missing main section"] = [f"มาตรา {n}" for n in range(1, mains[-1] + 1) if n not in present] if mains else []

    # มาตราย่อยขาดภายในชุด
    subs = defaultdict(set)
    for (n, s, _), _r in keys:
        if s:
            subs[n].add(s)
    for n, ss in subs.items():
        for s in range(1, max(ss) + 1):
            if s not in ss:
                problems["missing sub-section"].append(f"มาตรา {n}/{s}")

    # เนื้อหา
    for _, r in keys:
        c = r["content"].strip()
        if not c:
            problems["empty content"].append(r["section"])
        is_range_repeal = r.get("status") == "repealed" and re.fullmatch(
            r"มาตรา\s*[๐-๙]+\s*ถึง\s*มาตรา\s*[๐-๙]+\s*\(?\s*ยกเลิก\s*\)?", c)
        if not is_range_repeal and re.search(r"(^|\n)มาตรา\s*[๐-๙0-9]+\s", c):
            problems["possible merged sections"].append(r["section"])

    # ข้อความเพี้ยน
    if not args.no_text_check:
        from pythainlp import word_tokenize
        from pythainlp.corpus import thai_words
        words = thai_words()
        for _, r in keys:
            toks = [t for t in word_tokenize(r["content"], engine="newmm") if re.fullmatch(r"[ก-๏]{2,}", t)]
            if len(toks) >= 10:
                oov = [t for t in toks if t not in words]
                if len(oov) / len(toks) > OOV_LIMIT:
                    problems["garbled text"].append(f"{r['section']} ({len(oov)}/{len(toks)}: {' '.join(oov[:5])})")

    repealed = sum(1 for _, r in keys if r.get("status") == "repealed")
    print(f"Sections: {len(keys)}  (main numbers 1–{mains[-1] if mains else 0}, "
          f"sub-sections {sum(1 for k, _ in keys if k[1])}, ทวิ/ตรี {sum(1 for k, _ in keys if k[2])}, repealed {repealed})")

    failed = False
    for name in ["bad label", "duplicate", "out of order", "missing main section", "missing sub-section",
                 "empty content", "possible merged sections", "garbled text"]:
        items = problems.get(name, [])
        mark = "OK  " if not items else "FAIL"
        failed |= bool(items)
        print(f"[{mark}] {name}: {len(items)}")
        for it in items[:15]:
            print(f"        {it}")
        if len(items) > 15:
            print(f"        ... {len(items) - 15} more")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
