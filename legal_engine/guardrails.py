"""
Anti-Hallucination & Faithfulness Guardrails Engine
ระบบตรวจสอบความถูกต้องและป้องกันความคลาดเคลื่อนทางกฎหมาย (Grounding & Verification)
"""

import re
from typing import List, Dict, Any

class LegalGuardrails:
    def __init__(self):
        pass

    def verify_grounding(self, analysis_text: str, retrieved_statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        ตรวจสอบว่าผลการวิเคราะห์มีการอ้างอิงมาตราที่ถูกต้อง และไม่มีการแต่งข้อมูลเอง (Zero Hallucination Check)
        """
        # 1. กรณีไม่พบตัวบทกฎหมายที่เกี่ยวข้อง (Abstention Rule)
        if not retrieved_statutes:
            return {
                "passed": False,
                "is_abstention": True,
                "faithfulness_score": 0.0,
                "status": "ABSTAIN",
                "message": "ไม่พบตัวบทกฎหมายที่ตรงกับข้อเท็จจริงในฐานข้อมูล ระบบปฏิเสธการคาดคะเนเพื่อป้องกันความคลาดเคลื่อน",
                "verified_citations": [],
                "hallucinated_citations": [],
                "warnings": ["ไม่มีแหล่งอ้างอิงที่เชื่อถือได้ในฐานข้อมูล"]
            }

        # 2. ตรวจสอบการอ้างอิงเลขมาตราในบทวิเคราะห์ (Citation Check: รองรับทั้ง มาตรา N, ม. N, ม.N/N)
        mentioned_sections = set(re.findall(r'(?:มาตรา|ม\.)\s*(\d+(?:/\d+)?)', analysis_text))
        
        # เลขมาตราที่มีอยู่ในเอกสารอ้างอิงที่ค้นพบได้จริง
        valid_sections = set()
        for item in retrieved_statutes:
            statute = item["statute"]
            sec_match = re.search(r'\d+(?:/\d+)?', statute["section"])
            if sec_match:
                valid_sections.add(sec_match.group())

        verified_citations = list(mentioned_sections.intersection(valid_sections))
        hallucinated_citations = list(mentioned_sections - valid_sections)

        warnings = []
        if hallucinated_citations:
            warnings.append(f"ตรวจพบการอ้างอิงมาตราที่ไม่มีอยู่ในฐานข้อมูลอ้างอิง: มาตรา {', '.join(hallucinated_citations)}")

        # 3. คำนวณ Faithfulness Score
        # ถ้าระบุมาตราถูกต้องทั้งหมด และเนื้อหาสอดคล้องกับองค์ประกอบ
        base_score = 90.0
        if hallucinated_citations:
            base_score -= (len(hallucinated_citations) * 35.0)
            
        if verified_citations:
            base_score += 10.0
        else:
            warnings.append("บทวิเคราะห์ไม่ได้ระบุเลขมาตราอ้างอิงที่ชัดเจน")
            base_score -= 20.0

        faithfulness_score = max(0.0, min(100.0, round(base_score, 1)))

        passed = faithfulness_score >= 80.0 and len(hallucinated_citations) == 0

        status = "VERIFIED_ACCURATE" if passed else ("WARNING_UNVERIFIED" if faithfulness_score >= 50 else "FAILED_HALLUCINATION")

        return {
            "passed": passed,
            "is_abstention": False,
            "faithfulness_score": faithfulness_score,
            "status": status,
            "verified_citations": [f"มาตรา {s}" for s in verified_citations],
            "hallucinated_citations": [f"มาตรา {s}" for s in hallucinated_citations],
            "warnings": warnings,
            "audit_summary": {
                "total_referenced_statutes": len(retrieved_statutes),
                "top_statute": retrieved_statutes[0]["statute"]["section"] if retrieved_statutes else None,
                "confidence_level": "สูงมาก (High)" if faithfulness_score >= 90 else ("ปานกลาง (Medium)" if faithfulness_score >= 70 else "ต่ำ (Low)")
            }
        }
