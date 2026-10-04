# Software Requirements Specification (SRS)
## Thai Legal AI - Zero-Hallucination Legal Analysis & Summarization System

---

## 1. Executive Summary & Objectives

The primary objective of this system is to provide an enterprise-grade **Legal AI Assistant** specialized in Thai Law (Civil and Commercial Code, Criminal Code, Labor Laws, and PDPA). The system conducts rigorous legal analysis on factual statements and contracts, delivering precise summaries with a **strict zero-hallucination guarantee**.

Unlike general-purpose conversational LLMs that are prone to hallucinating citations or misinterpreting statutory nuances, this platform operates under a **Strict Grounding and Verification Architecture** (Hybrid RAG + FIRAC Reasoning + Real-time Citation Guardrails).

---

## 2. Functional Requirements (FR)

### FR-1: Legal Case & Contract Analysis (FIRAC Framework)
* **FR-1.1:** The system shall accept natural language inputs representing case facts, contract clauses, or legal disputes in Thai.
* **FR-1.2:** The system shall structure its analysis using the standard legal **FIRAC** methodology:
  * **Facts (F):** Objective synthesis of input facts without extrapolation.
  * **Issues (I):** Identification of concrete legal issues arising under Thai law.
  * **Rules (R):** Retrieval and presentation of authoritative statutory provisions (`มาตรา`), including verbatim text and legal elements.
  * **Application (A):** Systematic application of statutory elements to each factual aspect.
  * **Conclusion (C):** Definitive, non-hallucinatory legal summary and procedural rights.

### FR-2: Hybrid Legal Retrieval (BM25 + Semantic + PyThaiNLP)
* **FR-2.1:** The retrieval engine shall utilize **PyThaiNLP** (`newmm` engine) for accurate Thai morphological word segmentation.
* **FR-2.2:** The engine shall maintain a **Legal Synonym Dictionary** mapping common terminology (e.g., "รถ", "โกง", "ไล่ออก", "ข้อมูลรั่ว") to legal concepts ("ยานพาหนะ", "ฉ้อโกง", "เลิกจ้าง", "PDPA").
* **FR-2.3:** The engine shall implement **Hybrid Search** using **BM25Okapi** combined with exact statutory section bonuses (`มาตรา \d+`) to guarantee 100% recall for specific section citations.

### FR-3: Anti-Hallucination & Faithfulness Guardrails
* **FR-3.1:** The system shall inspect all generated outputs for cited section numbers.
* **FR-3.2:** If an output cites a section not present in the retrieved statutory context, the system shall flag it immediately as `FAILED_HALLUCINATION` and alert the user.
* **FR-3.3:** The system shall calculate a numerical **Faithfulness Score (0–100%)** measuring source grounding.
* **FR-3.4 (Abstention Policy):** If the retrieval confidence is below the minimum threshold, the system shall trigger the **Abstention Protocol** (`ABSTAIN`), explicitly refusing to guess or speculate.

### FR-4: Statute Knowledge Base & Ingestion
* **FR-4.1:** The system shall parse and index hierarchical legal documents (e.g., the complete Civil and Commercial Code from PDF/text sources).
* **FR-4.2:** Each statute shall be structured with unique ID, Category, Title, Section Number, Full Verbatim Text, Keywords, and Legal Elements.
* **FR-4.3:** The system shall provide an interactive **Statute Explorer** with instant search and filtering.

### FR-5: Dual-Engine Support
* **FR-5.1 (Deterministic Engine):** Offline, 100% grounded engine operating with zero latency and zero API cost.
* **FR-5.2 (External LLM API):** Secure integration with frontier models (OpenAI GPT-4o, Claude 3.5) with temperature set to `0.0`, strict system prompts, and post-generation guardrail validation.

---

## 3. Non-Functional Requirements (NFR)

* **NFR-1 (Accuracy & Reliability):** 0% tolerance for fabricated legal sections or invented precedents.
* **NFR-2 (Performance & Latency):** Sub-second retrieval (<100ms) for statutory search using in-memory BM25 indexing.
* **NFR-3 (Data Privacy & Security):** Client-side storage of external API keys (`localStorage`). No transmission of sensitive legal facts to third parties when using the Local Deterministic Engine.
* **NFR-4 (User Experience & Aesthetics):** High-end dark gold & navy glassmorphism web dashboard featuring responsive design, accessibility, and single-click legal test scenarios.
* **NFR-5 (Cross-Platform Compatibility):** Fully compatible with Windows, macOS, and Linux environments running Python 3.10+.

---

## 4. Technical Stack

| Component | Technology |
| :--- | :--- |
| **Backend Framework** | FastAPI (Python 3.13) |
| **ASGI Server** | Uvicorn |
| **Thai NLP & Tokenization** | PyThaiNLP (newmm engine) |
| **Information Retrieval** | Rank-BM25 + Custom Legal Lexicon |
| **Data Validation & Schemas** | Pydantic v2 |
| **Document Parser** | pdfplumber / PyMuPDF |
| **Frontend Architecture** | Modern Vanilla HTML5 / CSS3 (Glassmorphism) / ES6 JavaScript |
| **Typography** | Google Fonts (Prompt, Sarabun, Plus Jakarta Sans) |
