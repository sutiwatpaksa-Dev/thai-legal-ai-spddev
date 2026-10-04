"""
Hybrid Legal Retriever with PyThaiNLP (ระบบค้นหาตัวบทกฎหมายแบบผสม: BM25 + Semantic Matching)
ออกแบบมาสำหรับภาษาไทยและระบบกฎหมายโดยเฉพาะ เพื่อป้องกันการหลุดเลขมาตราและคำสำคัญเฉพาะ
"""

import re
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
from pythainlp import word_tokenize
from pythainlp.corpus import thai_stopwords
from .knowledge_base import LEGAL_STATUTES

_STOPWORDS = set(thai_stopwords())
_CUSTOM_IGNORE = {"นาย", "นาง", "นางสาว", "บริษัท", "ที่", "ซึ่ง", "อัน", "และ", "หรือ", "แต่", "ว่า", "นี้", "นั้น", "ได้", "ให้", "ไป", "มา", "มี", "เป็น", "อยู่", "จะ", "ก็", "ท่านว่า", "แห่ง", "ด้วย", "ใน", "ต่อ", "โดย"}
_ALL_STOPWORDS = _STOPWORDS.union(_CUSTOM_IGNORE)

# Legal Synonyms mapping (เพิ่มพจนานุกรมคำพ้องทางกฎหมาย)
LEGAL_SYNONYMS = {
    "รถ": ["ยานพาหนะ", "รถยนต์", "เครื่องจักรกล"],
    "รถยนต์": ["ยานพาหนะ", "เครื่องจักรกล", "รถ"],
    "ชน": ["ละเมิด", "เสียหาย", "อุบัติเหตุ", "ประมาทเลินเล่อ"],
    "บาดเจ็บ": ["ร่างกาย", "อนามัย", "อันตรายแก่กาย", "บาดเจ็บสาหัส", "รักษาตัว"],
    "บาดเจ็บสาหัส": ["ร่างกาย", "อนามัย", "อันตรายแก่กาย"],
    "โกง": ["ฉ้อโกง", "หลอกลวง", "ทุจริต", "แสดงข้อความอันเป็นเท็จ"],
    "หลอก": ["ฉ้อโกง", "หลอกลวง", "แสดงข้อความอันเป็นเท็จ"],
    "ขโมย": ["ลักทรัพย์", "เอาไป", "ทุจริต"],
    "เงินกู้": ["กู้ยืม", "หลักฐานเป็นหนังสือ"],
    "ไล่ออก": ["เลิกจ้าง", "ค่าชดเชย"],
    "ไล่": ["เลิกจ้าง", "ค่าชดเชย"],
    "ข้อมูลรั่ว": ["pdpa", "ข้อมูลส่วนบุคคล", "ความยินยอม"],
    "ประวัติการรักษา": ["ข้อมูลอ่อนไหว", "sensitive data", "ข้อมูลสุขภาพ", "pdpa"]
}

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

def extract_section_numbers(text: str) -> List[str]:
    """
    สกัดเลขมาตราจากข้อความ โดยต้องมีคำว่า 'มาตรา' หรือ 'ม.' นำหน้า (รองรับทั้งเลขไทยและเลขอารบิก)
    หรือกรณีข้อความเป็นตัวเลขเดี่ยวๆ ล้วน (เช่น '420', '๔๒๐', '1264/1')
    รองรับการระบุหลายมาตรา เช่น 'ม.420, 425', 'มาตรา 7 และ 224'
    """
    if not text:
        return []
    text_norm = text.translate(_THAI_DIGITS)
    stripped = text_norm.strip()
    if re.fullmatch(r'\d+(?:/\d+)?', stripped):
        return [stripped]
    sections = []
    # ค้นหามาตราที่มีคำนำหน้า 'มาตรา' หรือ 'ม.' และตัวเลขที่ตามหลัง (คั่นด้วย จุลภาค / และ / ถึง / -)
    for match in re.finditer(r'(?:มาตรา|ม\.)\s*(\d+(?:/\d+)?)((?:\s*(?:,|และ|ถึง|-)\s*\d+(?:/\d+)?)*)', text_norm):
        sections.append(match.group(1))
        rest = match.group(2)
        if rest:
            for extra in re.finditer(r'\d+(?:/\d+)?', rest):
                sections.append(extra.group())
    return sections

def tokenize_thai_legal(text: str) -> List[str]:
    """
    ตัดคำและสกัดคำสำคัญทางกฎหมายด้วย PyThaiNLP พร้อมขยายความหมายด้วย Legal Synonyms
    """
    if not text:
        return []

    # ดึงเลขมาตราเฉพาะที่มีคำนำหน้า มาตรา/ม. หรือเป็นตัวเลขเดี่ยวๆ
    section_matches = extract_section_numbers(text)
    
    # ตัดคำภาษาไทย
    raw_tokens = word_tokenize(text.lower(), engine="newmm")
    
    tokens = []
    for t in raw_tokens:
        t_clean = t.strip()
        if len(t_clean) > 1 and t_clean not in _ALL_STOPWORDS:
            tokens.append(t_clean)
            # เติมคำไวพจน์ทางกฎหมาย (Synonym expansion)
            if t_clean in LEGAL_SYNONYMS:
                tokens.extend(LEGAL_SYNONYMS[t_clean])

    # เพิ่ม tokens เลขมาตราโดยเฉพาะ
    for sec in section_matches:
        tokens.append(f"มาตรา{sec}")
        tokens.append(sec)

    return tokens

class HybridLegalRetriever:
    def __init__(self, statutes: List[Dict[str, Any]] = None):
        if statutes is None:
            try:
                from . import database as db
                db_statutes = db.list_statutes()
                statutes = db_statutes if db_statutes else LEGAL_STATUTES
            except Exception:
                statutes = LEGAL_STATUTES
        self.reload(statutes if statutes else LEGAL_STATUTES)

    def reload(self, statutes: List[Dict[str, Any]]) -> None:
        """สร้างดัชนี BM25 ใหม่ (เรียกเมื่อข้อมูลในฐานข้อมูลเปลี่ยนแปลง)"""
        self.statutes = statutes
        self.corpus_tokens = []
        for s in self.statutes:
            # รวมคำสำคัญ, เลขมาตรา, ชื่อหมวด และเนื้อหา
            combined_text = f"{s['category']} {s.get('book', '')} {s['title']} {s['section']} {' '.join(s['keywords'])} {' '.join(s['elements'])} {s['content']}"
            tokens = tokenize_thai_legal(combined_text)
            self.corpus_tokens.append(tokens)

        # BM25Okapi หารด้วยจำนวนเอกสาร จึงสร้างไม่ได้เมื่อคลังว่าง
        self.bm25 = BM25Okapi(self.corpus_tokens) if self.corpus_tokens else None

    def retrieve(self, query: str, top_k: int = 3, min_score_threshold: float = 1.0) -> List[Dict[str, Any]]:
        """
        ค้นหากฎหมายที่เกี่ยวข้องที่สุดโดยใช้ Hybrid Scoring
        หากคะแนนความเกี่ยวข้องต่ำกว่า min_score_threshold จะไม่ดึงข้อมูล (Abstention Rule)
        """
        query_tokens = tokenize_thai_legal(query)
        if not query_tokens or self.bm25 is None:
            return []

        # 1. BM25 Scores
        bm25_scores = self.bm25.get_scores(query_tokens)
        
        # 2. Section Exact Match Bonus (ต้องมีคำว่า 'มาตรา' หรือ 'ม.' นำหน้า เว้นแต่ค้นหาด้วยเลขเพียวๆ)
        query_sections = extract_section_numbers(query)
        
        unique_query_tokens = set(query_tokens)
        total_q_terms = len(unique_query_tokens)
        
        results = []
        for idx, s in enumerate(self.statutes):
            raw_bm25 = float(bm25_scores[idx])
            
            # ตรวจสอบ exact match เลขมาตรา
            section_bonus = 0.0
            statute_sec_match = re.search(r'\d+(?:/\d+)?', s['section'].translate(_THAI_DIGITS))
            if statute_sec_match and statute_sec_match.group() in query_sections:
                section_bonus = 25.0
                
            # ตรวจสอบ keyword overlap กับ keywords ของตัวบท (ตรวจสอบทั้งในข้อความและใน expanded tokens)
            matched_keywords = [kw for kw in s['keywords'] if kw.lower() in query.lower() or kw.lower() in query_tokens]
            kw_bonus = len(matched_keywords) * 4.0
            
            # คำนวณ Term Coverage (ป้องกันการจับคู่โดยบังเอิญจากคำเดียว เช่น "เดินทาง" ในคดีอวกาศ)
            corpus_set = set(self.corpus_tokens[idx])
            matched_q_terms = unique_query_tokens.intersection(corpus_set)
            coverage_ratio = len(matched_q_terms) / total_q_terms if total_q_terms else 0
            
            # หากข้อความค้นหามีหลายคำ แต่ไม่มี keyword ตรง และ coverage ต่ำกว่า 25% ให้ตัดออก (Spurious noise เช่น คดีอวกาศ)
            if total_q_terms >= 3 and not section_bonus:
                if not matched_keywords and coverage_ratio < 0.25:
                    continue
            
            final_score = raw_bm25 + section_bonus + kw_bonus
            
            if final_score >= min_score_threshold:
                # แปลงเป็น % ความเชื่อมั่น (Normalizing Confidence)
                norm_confidence = min(99.9, round(min(100.0, final_score * 6.5) + (15 if section_bonus > 0 else 0), 1))
                results.append({
                    "statute": s,
                    "score": round(final_score, 2),
                    "confidence": norm_confidence,
                    "matched_keywords": matched_keywords,
                    "is_exact_section": section_bonus > 0
                })
                
        # เรียงลำดับจากคะแนนสูงสุด
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_all_statutes(self) -> List[Dict[str, Any]]:
        return self.statutes
