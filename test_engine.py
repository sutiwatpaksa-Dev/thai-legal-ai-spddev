import sys
import json
sys.stdout.reconfigure(encoding='utf-8')
from legal_engine.legal_reasoner import LegalReasoner

reasoner = LegalReasoner()

print("\n--- Test 1: คดีละเมิดขับรถชน ---")
res1 = reasoner.analyze_facts("นายสมชายขับรถยนต์ด้วยความเร็วสูงฝ่าไฟแดงชนนายอนันต์บาดเจ็บสาหัส แขนหัก ต้องรักษาตัวในโรงพยาบาล")
print("Status:", res1["status"])
print("Faithfulness:", res1["guardrails"]["faithfulness_score"])
print("Statutes Cited:", res1["firac"]["statutes_cited"])
print("Conclusion:", res1["firac"]["conclusion"])

print("\n--- Test 2: คดีสัญญากู้ยืมเงิน ---")
res2 = reasoner.analyze_facts("นายดำกู้ยืมเงินจากนายขาวจำนวน 50,000 บาท โดยมีสัญญากู้ยืมเงินเป็นหนังสือลงลายมือชื่อนายดำไว้เป็นสำคัญ เมื่อถึงกำหนดชำระนายดำปฏิเสธไม่ยอมคืนเงิน")
print("Status:", res2["status"])
print("Statutes Cited:", res2["firac"]["statutes_cited"])
print("Conclusion:", res2["firac"]["conclusion"])

print("\n--- Test 3: ทดสอบ Abstention (คดีที่ไม่เกี่ยวข้องในฐานข้อมูล ป้องกันการเดา) ---")
res3 = reasoner.analyze_facts("การเดินทางไปดาวอังคารด้วยจรวดความเร็วเหนือเสียงโดยไม่ขออนุญาตองค์การอวกาศสากล")
print("Status:", res3["status"])
print("Is Abstention:", res3["guardrails"]["is_abstention"])
print("Conclusion:", res3["firac"]["conclusion"])
