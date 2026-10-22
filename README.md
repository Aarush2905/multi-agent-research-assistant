# Multi-Agent Research Assistant

A multi-stage, evidence-based academic research system. Given a research question, it decomposes the problem into sub-questions, searches scientific repositories and the web, retrieves and deeply analyzes literature, cross-examines findings, synthesizes an evidence-backed report with deterministic citations, and validates claim accuracy.

Powered by **Google Gemini** with a transparent, pure-Python 7-stage pipeline.

---

## The 7 Explicit Stages

Each stage has its own dedicated, readable file in `backend/app/`:

| Stage File | Stage Name | Description |
|---|---|---|
| `app/stage1_planning.py` | **1. Planning** | Decomposes question into sub-questions, classifies scientific domain, selects literature providers, and generates search queries (or requests user clarification if ambiguous). |
| `app/stage2_discovery.py` | **2. Discovery** | Concurrently queries arXiv, PubMed, Semantic Scholar, Patents, and Tavily Web; normalizes, deduplicates, and ranks sources. |
| `app/stage3_retrieval.py` | **3. Retrieval** | Fetches full-text content (PDF / HTML) using PyMuPDF and BeautifulSoup, with automatic abstract fallback. |
| `app/stage4_analysis.py` | **4. Analysis** | Analyzes each document individually to extract claims, direct quotes, quantitative metrics, and limitations. |
| `app/stage5_cross_analysis.py` | **5. Cross-Source Analysis** | Compares evidence across all sources to map consensus, disputes, limitations, and research gaps. |
| `app/stage6_synthesis.py` | **6. Synthesis** | Writes the research report and deterministically assigns verifiable citation badges (`C1`, `C2`, ...). |
| `app/stage7_validation.py` | **7. Validation** | Checks citation integrity deterministically and evaluates evidence support via Gemini, triggering bounded synthesis repairs if needed. |

---

## Backend File Layout

```text
backend/app/
├── stage1_planning.py       # Stage 1: Decomposition & Query Planning
├── stage2_discovery.py      # Stage 2: Multi-source search & deduplication
├── stage3_retrieval.py      # Stage 3: PDF / HTML fetching & text extraction
├── stage4_analysis.py       # Stage 4: Per-document structured claim extraction
├── stage5_cross_analysis.py # Stage 5: Cross-source agreements & research gaps
├── stage6_synthesis.py      # Stage 6: Report drafting & deterministic citations
├── stage7_validation.py     # Stage 7: Citation checking & evidence validation
├── pipeline.py              # Pure async Python orchestrator connecting Stages 1 -> 7
├── models.py                # All Pydantic data schemas in one unified place
├── gemini.py                # Gemini API client with structured JSON parsing & retries
├── export.py                # PDF report generator using ReportLab
├── config.py                # App configuration loaded from .env
└── main.py                  # FastAPI server, REST API endpoints, and SQLite storage
```

---

## Quickstart

### 1. Configuration
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY="your-gemini-api-key-here"
```
*(Optional: `TAVILY_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `NCBI_API_KEY`)*

### 2. Run Backend
```bash
cd backend
source .venv/bin/activate       # macOS/Linux (or .venv\Scripts\activate on Windows)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
- API Docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

### 3. Run Frontend
```bash
cd frontend
npm install
npm run dev
```
- Web Dashboard: http://localhost:5173

---

## Running Tests

```bash
# Backend unit tests
cd backend
pytest

# Frontend component tests
cd frontend
npm test
```
