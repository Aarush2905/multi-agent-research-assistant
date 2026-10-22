"""Stage 4: Document Analysis.

Extracts structured scientific evidence from each retrieved document:
- Key claims with direct supporting quotes and confidence scores
- Research methodologies used
- Quantitative metrics with units and experimental context
- Stated limitations
"""

from __future__ import annotations

import asyncio
import logging

from app.gemini import GeminiGenerationError, generate_structured
from app.models import (
    ResearchPlan,
    RetrievalStatus,
    RetrievedDocument,
    Source,
    SourceAnalysis,
)

logger = logging.getLogger(__name__)

_ANALYSIS_SYSTEM = (
    "You extract structured evidence from a single retrieved academic document. "
    "Only report findings, methods, metrics and limitations that are actually present "
    "in the provided text - NEVER hallucinate or invent data, statistics, or claims. "
    "If the text is too short or insufficient, note this in analysis_warnings. "
    "Each key finding should include a direct supporting_quote from the text."
)

_MAX_INPUT_CHARS = 40_000


def analyze_single_document(
    source: Source, document: RetrievedDocument | None, plan: ResearchPlan
) -> SourceAnalysis:
    """Extract claims, metrics, and methods from a single document."""
    text = ""
    if document and document.retrieval_status == RetrievalStatus.SUCCESS and document.full_text:
        text = document.full_text[:_MAX_INPUT_CHARS]
    elif source.abstract:
        text = source.abstract
    else:
        return SourceAnalysis(
            source_id=source.source_id,
            analysis_warnings=["No retrievable full text or abstract available for analysis."],
        )

    sub_questions = "\n".join(f"- {q.text}" for q in plan.sub_questions) or "(none provided)"
    prompt = (
        f"Research question: {plan.research_question}\n\n"
        f"Sub-questions:\n{sub_questions}\n\n"
        f"Document title: {source.title}\n"
        f"Document text:\n{text}\n\n"
        "Extract key findings (with supporting quotes), methodologies, quantitative metrics, "
        "and stated limitations. Map relevant sub-questions to a short summary of how this paper addresses them."
    )

    try:
        analysis = generate_structured(prompt, SourceAnalysis, system_instruction=_ANALYSIS_SYSTEM)
        analysis.source_id = source.source_id
        return analysis
    except GeminiGenerationError as exc:
        logger.warning("Analysis failed for source %s: %s", source.source_id, exc)
        return SourceAnalysis(
            source_id=source.source_id,
            analysis_warnings=[f"Automated extraction failed: {exc}"],
        )


async def run_analysis(
    sources: list[Source],
    documents: list[RetrievedDocument],
    plan: ResearchPlan,
) -> list[SourceAnalysis]:
    """Analyze all retrieved documents concurrently."""
    docs_by_id = {d.source_id: d for d in documents}
    tasks = [
        asyncio.to_thread(analyze_single_document, s, docs_by_id.get(s.source_id), plan)
        for s in sources
    ]
    analyses = await asyncio.gather(*tasks)
    return list(analyses)
