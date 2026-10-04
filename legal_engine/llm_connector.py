"""
LLM Connector for External Models (OpenAI, Claude, Ollama, Groq) with Strict Grounding
รองรับการเชื่อมต่อกับโมเดลภายนอก พร้อมการควบคุม Prompt ป้องกัน Hallucination อย่างเข้มงวด
"""

import json
from typing import Dict, Any, List

class LegalLLMConnector:
    def __init__(self, api_key: str = None, provider: str = "openai", base_url: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.provider = provider
        self.base_url = base_url
        self.model = model

    def build_system_prompt(self, statutes: List[Dict[str, Any]]) -> str:
        statute_contexts = []
        for item in statutes:
            s = item["statute"] if "statute" in item else item
            statute_contexts.append(
                f"- [{s['category']} {s['section']} - {s['title']}]:\n  เนื้อหา: {s['content']}\n  องค์ประกอบ: {', '.join(s['elements'])}"
            )
            
        context_str = "\n\n".join(statute_contexts)
        
        return f"""คุณคือผู้ช่วยวิเคราะห์กฎหมายไทยระดับผู้เชี่ยวชาญ (Strict Legal AI)
หน้าที่ของคุณคือวิเคราะห์ข้อเท็จจริงและให้บทสรุปตามหลัก FIRAC โดย "ห้ามคาดเดา ห้ามเติมแต่ง และห้ามอ้างอิงมาตราที่ไม่มีอยู่ในบริบทที่กำหนดให้เด็ดขาด"

[ฐานข้อมูลตัวบทกฎหมายที่อนุญาตให้อ้างอิงได้เท่านั้น]:
{context_str}

[กฎเหล็กในการตอบเพื่อป้องกันความคลาดเคลื่อน (Zero Hallucination Rules)]:
1. อ้างอิงเฉพาะเลขมาตราที่ปรากฏในฐานข้อมูลข้างต้นเท่านั้น
2. ทุกข้อสรุปต้องระบุเลขมาตรากำกับเสมอ เช่น [ป.พ.พ. มาตรา 420]
3. หากข้อเท็จจริงไม่เข้าข่ายตัวบทใดในฐานข้อมูล ให้ตอบว่า "ไม่พบข้อกฎหมายที่ตรงในฐานข้อมูล" ห้ามประดิษฐ์ข้อกฎหมายเอง
4. ตอบในรูปแบบ JSON ที่มี key:
   - "legal_issue": ประเด็นข้อกฎหมายหลัก
   - "rules_applied": รายการมาตราที่นำมาปรับบท
   - "application": การปรับข้อเท็จจริงเข้ากับองค์ประกอบ
   - "conclusion": บทสรุปที่กระชับ แม่นยำ และชัดเจน
"""

    def call_llm(self, facts: str, statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        เรียก LLM ผ่าน OpenAI API (หากมี API key)
        """
        if not self.api_key:
            return {"error": "No API Key provided"}

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            system_prompt = self.build_system_prompt(statutes)
            
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.0,  # กำหนดเป็น 0.0 เพื่อลดความสุ่มและเพิ่มความแม่นยำสูงสุด
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"ข้อเท็จจริง: {facts}"}
                ]
            )
            
            raw_content = response.choices[0].message.content
            return json.loads(raw_content)
        except Exception as e:
            return {"error": str(e)}
