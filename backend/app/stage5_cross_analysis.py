"""Stage 5: Cross-Source Analysis.

Compares findings across all analyzed sources to identify:
- Points of consensus / agreement between authors
- Conflicts / disagreements in findings or methodologies
- Evidence limitations of the collective literature
- Open research gaps that remain unaddressed
"""

from __future__ import annotations

import json
import logging

from app.gemini import GeminiGenerationError, generate_structured
from app.models import (
    CrossSourceAnalysis,
    ResearchPlan,
    SourceAnalysis,
)

logger = logging.getLogger(__name__)

_CROSS_SYSTEM = (
    "You compare structured findings extracted from multiple academic sources. "
    "Identify where sources agree, where they disagree, collective limitations of the evidence, "
    "and research gaps where the sub-questions lack sufficient evidence. "
    "Reference source_ids EXACTLY as given - never invent a source_id. "
    "Base every statement solely on the provided findings."
)

_MAX_FINDINGS_PER_SOURCE = 8


def run_cross_analysis(analyses: list[SourceAnalysis], plan: ResearchPlan) -> CrossSourceAnalysis:
    """Compare evidence across multiple source analyses."""
    usable = [a for a in analyses if a.key_findings or a.metrics]
    if not usable:
        return CrossSourceAnalysis(
            evidence_limitations=["No sources yielded extractable evidence; cross-source comparison was skipped."]
        )

    condensed = [
        {
            "source_id": a.source_id,
            "key_findings": [f.text for f in a.key_findings[:_MAX_FINDINGS_PER_SOURCE]],
            "metrics": [f"{m.name}: {m.value} {m.unit or ''}".strip() for m in a.metrics],
            "limitations": a.limitations,
        }
        for a in usable
    ]
    sub_questions = [q.text for q in plan.sub_questions]

    prompt = (
        f"Research question: {plan.research_question}\n\n"
        f"Sub-questions: {json.dumps(sub_questions)}\n\n"
        f"Per-source findings:\n{json.dumps(condensed, indent=2)}\n\n"
        "Analyze agreements across sources, disagreements, collective limitations, and research gaps."
    )

    try:
        return generate_structured(prompt, CrossSourceAnalysis, system_instruction=_CROSS_SYSTEM)
    except GeminiGenerationError as exc:
        logger.warning("Cross-source analysis failed: %s", exc)
        return CrossSourceAnalysis(
            evidence_limitations=[f"Automated cross-source comparison failed: {exc}"]
        )
