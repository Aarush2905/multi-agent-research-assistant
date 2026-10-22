"""Stage 6: Synthesis.

Synthesizes a cohesive, evidence-backed research report from the analyzed literature
and cross-source findings, deterministically assigning verified citation badges (C1, C2, ...).
"""

from __future__ import annotations

import json
import logging
from pydantic import BaseModel, Field

from app.gemini import GeminiGenerationError, generate_structured
from app.models import (
    Citation,
    CrossSourceAnalysis,
    ReportSection,
    ReportSummary,
    ResearchPlan,
    ResearchReport,
    Source,
    SourceAnalysis,
)

logger = logging.getLogger(__name__)

_SYNTHESIS_SYSTEM = (
    "You write a comprehensive, evidence-based academic research report from the provided sources. "
    "Every factual claim MUST be attributed to a valid source_id from the provided list. "
    "NEVER invent citations, authors, findings, or metrics not present in the evidence. "
    "Organize sections logically around the sub-questions and key themes. "
    "Write in objective, rigorous, publication-quality prose."
)


class _DraftSection(BaseModel):
    heading: str
    body: str
    source_ids: list[str] = Field(default_factory=list)


class _DraftReport(BaseModel):
    title: str
    executive_summary: str
    executive_summary_source_ids: list[str] = Field(default_factory=list)
    sections: list[_DraftSection] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)


def _condense_evidence(sources: list[Source], analyses: list[SourceAnalysis]) -> list[dict]:
    analyses_by_id = {a.source_id: a for a in analyses}
    condensed = []
    for s in sources:
        a = analyses_by_id.get(s.source_id)
        condensed.append(
            {
                "source_id": s.source_id,
                "title": s.title,
                "authors": s.authors[:4],
                "year": s.publication_year,
                "provider": s.provider.value,
                "key_findings": [f.text for f in a.key_findings] if a else [],
                "metrics": [f"{m.name}: {m.value} {m.unit or ''}".strip() for m in a.metrics] if a else [],
                "limitations": a.limitations if a else [],
            }
        )
    return condensed


def _assign_citations_deterministically(
    draft: _DraftReport, valid_source_ids: set[str], research_question: str
) -> ResearchReport:
    """Deterministically maps source_ids to C1, C2... in order of appearance in the report."""
    assigned: dict[str, str] = {}

    def to_citation_ids(source_ids: list[str]) -> list[str]:
        result = []
        for sid in source_ids:
            if sid not in valid_source_ids:
                continue
            if sid not in assigned:
                assigned[sid] = f"C{len(assigned) + 1}"
            cid = assigned[sid]
            if cid not in result:
                result.append(cid)
        return result

    summary_citation_ids = to_citation_ids(draft.executive_summary_source_ids)
    sections = [
        ReportSection(
            heading=s.heading,
            body=s.body,
            citation_ids=to_citation_ids(s.source_ids),
        )
        for s in draft.sections
    ]

    citations = [Citation(citation_id=cid, source_id=sid) for sid, cid in assigned.items()]

    return ResearchReport(
        title=draft.title,
        research_question=research_question,
        executive_summary=ReportSummary(text=draft.executive_summary, citation_ids=summary_citation_ids),
        sections=sections,
        limitations=draft.limitations,
        research_gaps=draft.research_gaps,
        citations=citations,
    )


def run_synthesis(
    plan: ResearchPlan,
    sources: list[Source],
    analyses: list[SourceAnalysis],
    cross_analysis: CrossSourceAnalysis,
    repair_feedback: list[str] | None = None,
) -> ResearchReport:
    """Synthesize the final research report with verifiable citations."""
    valid_ids = {s.source_id for s in sources}
    evidence = _condense_evidence(sources, analyses)

    repair_prompt = ""
    if repair_feedback:
        repair_prompt = (
            "\nNote: The previous draft had the following validation issues. Fix them in this draft:\n"
            + "\n".join(f"- {issue}" for issue in repair_feedback)
            + "\n"
        )

    prompt = (
        f"Research Question:\n{plan.research_question}\n\n"
        f"Sub-questions:\n{json.dumps([q.text for q in plan.sub_questions])}\n\n"
        f"Evidence Collected:\n{json.dumps(evidence, indent=2)}\n\n"
        f"Cross-Source Agreements:\n{json.dumps([a.model_dump() for a in cross_analysis.agreements])}\n"
        f"Cross-Source Disagreements:\n{json.dumps([d.model_dump() for d in cross_analysis.disagreements])}\n"
        f"Research Gaps:\n{json.dumps([g.model_dump() for g in cross_analysis.research_gaps])}\n\n"
        f"Allowed source_ids for citation: {json.dumps(sorted(valid_ids))}\n"
        f"{repair_prompt}\n"
        "Generate the complete research report draft now."
    )

    try:
        draft = generate_structured(prompt, _DraftReport, system_instruction=_SYNTHESIS_SYSTEM, temperature=0.3)
    except GeminiGenerationError as exc:
        logger.error("Report synthesis failed: %s", exc)
        draft = _DraftReport(
            title=f"Research Report: {plan.research_question}",
            executive_summary="Report synthesis could not complete due to generation error.",
            limitations=[f"Synthesis failed: {exc}"],
        )

    return _assign_citations_deterministically(draft, valid_ids, plan.research_question)
