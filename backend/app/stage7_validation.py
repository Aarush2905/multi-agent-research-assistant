"""Stage 7: Validation.

Validates report integrity:
1. Deterministic Citation Checking: Ensures every citation used in sections/summary exists
   in the references list and points to a real, retrieved source.
2. Evidence Support Checking (LLM-assisted): Verifies that stated claims and metrics are
   genuinely supported by the cited findings.
"""

from __future__ import annotations

import json
import logging
from pydantic import BaseModel, Field

from app.gemini import GeminiGenerationError, generate_structured
from app.models import (
    ResearchReport,
    Source,
    SourceAnalysis,
    ValidationIssue,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Deterministic Citation Check
# ---------------------------------------------------------------------------

def check_citations(report: ResearchReport, sources: list[Source]) -> list[ValidationIssue]:
    """Verify that all citations in the report are defined and point to retrieved sources."""
    issues: list[ValidationIssue] = []
    valid_source_ids = {s.source_id for s in sources}
    citation_to_source = {c.citation_id: c.source_id for c in report.citations}

    # Check that defined citations point to valid retrieved sources
    for citation_id, source_id in citation_to_source.items():
        if source_id not in valid_source_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    description=f"Citation {citation_id} points to source_id '{source_id}' which was not among the retrieved sources.",
                    citation_id=citation_id,
                )
            )

    # Check for uncited sections
    used_citation_ids: set[str] = set(report.executive_summary.citation_ids)
    for section in report.sections:
        used_citation_ids.update(section.citation_ids)
        if not section.citation_ids:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    description=f"Section '{section.heading}' makes claims with no citations.",
                    section_heading=section.heading,
                )
            )

    # Check for undefined citations used in text
    for citation_id in used_citation_ids:
        if citation_id not in citation_to_source:
            issues.append(
                ValidationIssue(
                    severity="error",
                    description=f"Citation {citation_id} is referenced in text but was never defined in references.",
                    citation_id=citation_id,
                )
            )

    return issues


# ---------------------------------------------------------------------------
# 2. LLM Evidence Support Check
# ---------------------------------------------------------------------------

_EVIDENCE_SYSTEM = (
    "You check whether statements in a research report are actually supported by "
    "the evidence provided for their citations. Flag any sentence that makes a "
    "specific factual or statistical claim not backed by the cited sources' findings. "
    "Be concise - report only genuine mismatches or unsupported claims."
)


class _EvidenceCheckOutput(BaseModel):
    unsupported_claims: list[str] = Field(default_factory=list)
    unsupported_section_headings: list[str] = Field(default_factory=list)


def check_evidence_support(
    report: ResearchReport, sources: list[Source], analyses: list[SourceAnalysis]
) -> list[ValidationIssue]:
    """Verify if the claims in each section match the cited sources' findings."""
    analyses_by_id = {a.source_id: a for a in analyses}
    citation_to_source = {c.citation_id: c.source_id for c in report.citations}

    sections_payload = []
    for section in report.sections:
        cited_findings = []
        for cid in section.citation_ids:
            sid = citation_to_source.get(cid)
            a = analyses_by_id.get(sid) if sid else None
            if a:
                cited_findings.extend(f.text for f in a.key_findings)
        sections_payload.append(
            {
                "heading": section.heading,
                "body": section.body,
                "cited_findings": cited_findings,
            }
        )

    if not sections_payload:
        return []

    prompt = (
        f"Report sections with their cited evidence:\n"
        f"{json.dumps(sections_payload, indent=2)}\n\n"
        "List any unsupported claims and the section headings they appear in."
    )

    try:
        result = generate_structured(prompt, _EvidenceCheckOutput, system_instruction=_EVIDENCE_SYSTEM)
    except GeminiGenerationError as exc:
        logger.warning("Evidence-support check failed: %s", exc)
        return [
            ValidationIssue(
                severity="warning",
                description=f"Automated evidence-support check could not run: {exc}",
            )
        ]

    issues: list[ValidationIssue] = []
    for claim, heading in zip(
        result.unsupported_claims,
        result.unsupported_section_headings or [None] * len(result.unsupported_claims),
    ):
        issues.append(
            ValidationIssue(
                severity="error",
                description=f"Possibly unsupported claim: {claim}",
                section_heading=heading,
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Stage 7 Orchestrator
# ---------------------------------------------------------------------------

def run_validation(
    report: ResearchReport,
    sources: list[Source],
    analyses: list[SourceAnalysis],
    attempt: int = 1,
) -> ValidationResult:
    """Execute complete validation over the drafted report."""
    issues = check_citations(report, sources)
    evidence_issues = check_evidence_support(report, sources, analyses)
    issues.extend(evidence_issues)

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationResult(
        passed=not has_errors,
        issues=issues,
        repair_attempt=attempt,
    )
