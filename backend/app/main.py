"""FastAPI application entrypoint for the Multi-Agent Research Assistant.

Provides REST endpoints matching the React frontend contract:
- Create, inspect, clarify, and cancel research runs
- Inspect and export reports as publication-quality PDFs
- Grounded follow-up Q&A against retrieved evidence
- Gemini connectivity and health status
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import get_settings
from app.export import render_report_pdf
from app.gemini import generate_structured, test_auth
from app.models import (
    Citation,
    FollowUpExchange,
    ResearchReport,
    ResearchState,
    RunStatus,
    Source,
    SourceAnalysis,
    new_state,
    serialize_state,
)
from app.pipeline import run_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("research_assistant")

_DB_PATH = Path(__file__).resolve().parents[1] / "research.db"


# ---------------------------------------------------------------------------
# Lightweight SQLite Storage
# ---------------------------------------------------------------------------

def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_db_connection()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                research_question TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS follow_ups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citation_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
    conn.close()


# Ensure tables exist immediately on import
init_db()


def db_save_run(run_id: str, question: str, status: str, state: dict):
    conn = _get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, research_question, status, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status = excluded.status,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at;
            """,
            (run_id, question, status, json.dumps(state), now, now),
        )
    conn.close()


def db_get_run(run_id: str) -> dict | None:
    conn = _get_db_connection()
    cursor = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "run_id": row["run_id"],
        "research_question": row["research_question"],
        "status": row["status"],
        "state": json.loads(row["state_json"]),
        "created_at": row["created_at"],
    }


def db_add_follow_up(run_id: str, question: str, answer: str, citation_ids: list[str]):
    conn = _get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO follow_ups (run_id, question, answer, citation_ids_json, created_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (run_id, question, answer, json.dumps(citation_ids), now),
        )
    conn.close()


def db_list_follow_ups(run_id: str) -> list[dict]:
    conn = _get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM follow_ups WHERE run_id = ? ORDER BY id ASC", (run_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "question": r["question"],
            "answer": r["answer"],
            "citation_ids": json.loads(r["citation_ids_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# API Request / Response Schemas
# ---------------------------------------------------------------------------

class CreateRunRequest(BaseModel):
    research_question: str


class CreateRunResponse(BaseModel):
    run_id: str
    status: str


class ClarifyRequest(BaseModel):
    clarification_response: str


class FollowUpRequest(BaseModel):
    question: str


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    research_question: str
    state: dict


# ---------------------------------------------------------------------------
# Follow-up Q&A Logic
# ---------------------------------------------------------------------------

class _FollowUpAnswer(BaseModel):
    answer: str
    source_ids: list[str] = []


def answer_follow_up_question(
    question: str,
    report: ResearchReport,
    sources: list[Source],
    analyses: list[SourceAnalysis],
) -> tuple[str, list[str]]:
    valid_ids = {s.source_id for s in sources}
    analyses_by_id = {a.source_id: a for a in analyses}
    evidence = [
        {
            "source_id": s.source_id,
            "title": s.title,
            "key_findings": [f.text for f in analyses_by_id[s.source_id].key_findings]
            if s.source_id in analyses_by_id
            else [],
        }
        for s in sources
    ]

    system_instruction = (
        "You answer a follow-up question about a completed research report using ONLY the evidence "
        "already collected. Cite the source_ids you rely on. If the existing evidence does not "
        "answer the question, say so plainly rather than hallucinating or using outside knowledge."
    )

    prompt = (
        f"Report title: {report.title}\n"
        f"Executive summary: {report.executive_summary.text}\n\n"
        f"Evidence Collected:\n{json.dumps(evidence, indent=2)}\n\n"
        f"Follow-up Question: {question}\n\n"
        f"Valid source_ids you may cite: {json.dumps(sorted(valid_ids))}"
    )

    try:
        output = generate_structured(prompt, _FollowUpAnswer, system_instruction=system_instruction)
    except Exception as exc:
        return f"Could not generate an answer: {exc}", []

    source_to_citation = {c.source_id: c.citation_id for c in report.citations}
    next_idx = len(report.citations) + 1
    citation_ids = []
    for sid in output.source_ids:
        if sid in valid_ids:
            if sid in source_to_citation:
                cid = source_to_citation[sid]
            else:
                cid = f"C{next_idx}"
                next_idx += 1
                source_to_citation[sid] = cid
                report.citations.append(Citation(citation_id=cid, source_id=sid))
            if cid not in citation_ids:
                citation_ids.append(cid)

    return output.answer, citation_ids


# ---------------------------------------------------------------------------
# App Lifespan & Initialization
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("SQLite research database initialized at %s", _DB_PATH)

    ok, message = await test_auth()
    if ok:
        logger.info(message)
    else:
        logger.warning("Gemini startup status: %s", message)
    yield


app = FastAPI(title="Multi-Agent Research Assistant", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/gemini/status")
async def gemini_status():
    ok, message = await test_auth()
    return {"ok": ok, "message": message}


@app.post("/api/research", response_model=CreateRunResponse, status_code=201)
async def create_research_run(payload: CreateRunRequest):
    question = payload.research_question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="research_question must not be empty")

    run_id = str(uuid.uuid4())
    initial_state = new_state(run_id, question)
    db_save_run(run_id, question, "pending", serialize_state(dict(initial_state)))

    async def _on_progress(status: RunStatus, state: ResearchState):
        db_save_run(run_id, question, status.value, serialize_state(dict(state)))

    run_manager.launch(run_id, initial_state, _on_progress)
    return CreateRunResponse(run_id=run_id, status="pending")


@app.get("/api/research/{run_id}", response_model=RunStatusResponse)
async def get_research_run(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    return RunStatusResponse(
        run_id=run["run_id"],
        status=run["status"],
        research_question=run["research_question"],
        state=run["state"],
    )


@app.post("/api/research/{run_id}/clarify", response_model=CreateRunResponse)
async def clarify_research_run(run_id: str, payload: ClarifyRequest):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    if run["status"] != "awaiting_clarification":
        raise HTTPException(status_code=409, detail="This run is not awaiting clarification")

    state = new_state(run_id, run["research_question"])
    state["clarification_response"] = payload.clarification_response.strip()

    async def _on_progress(status: RunStatus, s: ResearchState):
        db_save_run(run_id, run["research_question"], status.value, serialize_state(dict(s)))

    run_manager.launch(run_id, state, _on_progress)
    return CreateRunResponse(run_id=run_id, status="planning")


@app.post("/api/research/{run_id}/cancel", response_model=CreateRunResponse)
async def cancel_research_run(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    run_manager.cancel(run_id)
    state = run["state"]
    state["status"] = "cancelled"
    db_save_run(run_id, run["research_question"], "cancelled", state)
    return CreateRunResponse(run_id=run_id, status="cancelled")


@app.get("/api/research/{run_id}/report")
async def get_research_report(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    report = run["state"].get("report")
    if not report:
        raise HTTPException(status_code=409, detail="This run does not have a completed report yet")
    return report


@app.get("/api/research/{run_id}/export/pdf")
async def export_research_report_pdf(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    state = run["state"]
    report_data = state.get("report")
    if not report_data:
        raise HTTPException(status_code=409, detail="This run does not have a completed report yet")

    report = ResearchReport.model_validate(report_data)
    sources = [Source.model_validate(s) for s in state.get("sources", [])]
    pdf_bytes = render_report_pdf(report, sources)

    filename = f"research_report_{run_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/research/{run_id}/followup")
async def ask_followup(run_id: str, payload: FollowUpRequest):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    state = run["state"]
    report_data = state.get("report")
    if not report_data:
        raise HTTPException(status_code=409, detail="Cannot ask follow-up questions before report is generated")

    report = ResearchReport.model_validate(report_data)
    sources = [Source.model_validate(s) for s in state.get("sources", [])]
    analyses = [SourceAnalysis.model_validate(a) for a in state.get("source_analyses", [])]

    answer, citation_ids = answer_follow_up_question(payload.question, report, sources, analyses)
    db_add_follow_up(run_id, payload.question, answer, citation_ids)

    return {
        "question": payload.question,
        "answer": answer,
        "citation_ids": citation_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/research/{run_id}/followups")
async def get_followups(run_id: str):
    run = db_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Research run not found")
    return db_list_follow_ups(run_id)
