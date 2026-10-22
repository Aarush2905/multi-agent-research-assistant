"""Stage 1: Planning.

Decomposes the research question into focused sub-questions, classifies the
scientific/academic domain, determines relevant literature repositories, and generates
targeted search queries. Pauses for user clarification if the question is ambiguous.
"""

from __future__ import annotations

import logging
import re
from pydantic import BaseModel, Field

from app.config import Settings
from app.gemini import GeminiGenerationError, generate_structured
from app.models import (
    Domain,
    DomainClassification,
    ResearchPlan,
    SearchQuery,
    SourceProvider,
    SubQuestion,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step 1A: Question Decomposition
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = (
    "You are the planning stage of an evidence-based research assistant. You decompose "
    "a research question into 2-8 focused, non-overlapping sub-questions. Do not answer "
    "the question yourself. If the question is too ambiguous to research (e.g., missing "
    "a clear subject, wildly underspecified), set needs_clarification=true and provide "
    "one focused clarification question instead of guessing."
)


class DecomposeOutput(BaseModel):
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    warnings: list[str] = Field(default_factory=list)


def decompose_question(research_question: str) -> DecomposeOutput:
    prompt = (
        f"Research question:\n{research_question}\n\n"
        "Decompose it into 2-8 distinct, non-overlapping, researchable sub-questions "
        "(or request clarification if it is too ambiguous)."
    )
    return generate_structured(prompt, DecomposeOutput, system_instruction=_DECOMPOSE_SYSTEM)


# ---------------------------------------------------------------------------
# Step 1B: Domain Classification
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You classify a research question into one primary domain and zero or more secondary domains, "
    "using ONLY the enum values provided in the schema. Also select which of the allowed "
    "source providers are relevant (arxiv, pubmed, semantic_scholar, patents, web) and suggested "
    "document types. Keep interdisciplinary questions broad rather than forcing a single narrow domain."
)


def classify_domain(research_question: str, sub_questions: list[SubQuestion]) -> DomainClassification:
    sub_q_text = "\n".join(f"- {q.text}" for q in sub_questions) or "(none)"
    prompt = (
        f"Research question:\n{research_question}\n\n"
        f"Sub-questions:\n{sub_q_text}\n\n"
        "Classify the domain(s), select relevant source providers, and suggest document types."
    )
    return generate_structured(prompt, DomainClassification, system_instruction=_CLASSIFY_SYSTEM)


# ---------------------------------------------------------------------------
# Step 1C: Search Query Generation
# ---------------------------------------------------------------------------

_QUERY_SYSTEM = (
    "You generate focused search queries for academic and scientific search engines. "
    "Use domain-appropriate terminology and keywords. For each query, specify which "
    "source providers it targets (arxiv, pubmed, semantic_scholar, patents, web). "
    "CRITICAL for PubMed: PubMed uses strict Boolean AND across all terms, so queries "
    "targeting PubMed MUST be concise (3 to 5 focused keywords, e.g. 'neural decoding brain computer interface'), "
    "never long descriptive sentences. "
    "Prefer fewer, high-quality, distinct queries over many redundant ones."
)


class QueryGenOutput(BaseModel):
    queries: list[SearchQuery] = Field(default_factory=list)


def _normalize_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _dedup_and_limit(
    queries: list[SearchQuery], allowed_sources: list, max_queries: int
) -> list[SearchQuery]:
    allowed = set(allowed_sources) or None
    seen: set[str] = set()
    deduped: list[SearchQuery] = []
    for q in queries:
        key = _normalize_title(q.text)
        if not key or key in seen:
            continue
        targets = [s for s in q.target_sources if not allowed or s in allowed]
        if not targets:
            continue
        q.target_sources = targets
        seen.add(key)
        deduped.append(q)
        if len(deduped) >= max_queries:
            break
    return deduped


def generate_search_queries(
    research_question: str,
    sub_questions: list[SubQuestion],
    classification: DomainClassification,
    max_queries: int,
    temperature: float | None = None,
) -> list[SearchQuery]:
    sub_q_text = "\n".join(f"- {q.text}" for q in sub_questions) or "(none)"
    providers = ", ".join(p.value for p in classification.relevant_sources) or "web"
    prompt = (
        f"Research question:\n{research_question}\n\n"
        f"Sub-questions:\n{sub_q_text}\n\n"
        f"Relevant source providers: {providers}\n\n"
        f"Generate at most {max_queries} focused search queries. Each query must target "
        "one or more of the relevant source providers listed above."
    )
    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    output = generate_structured(prompt, QueryGenOutput, system_instruction=_QUERY_SYSTEM, **kwargs)
    return _dedup_and_limit(output.queries, classification.relevant_sources, max_queries)


# ---------------------------------------------------------------------------
# Stage 1 Orchestrator
# ---------------------------------------------------------------------------

def run_planning(
    research_question: str, settings: Settings, clarification_response: str | None = None
) -> ResearchPlan:
    """Execute Stage 1: Decomposition -> Classification -> Query Generation."""
    effective_question = research_question
    if clarification_response:
        effective_question = f"{research_question}\n\nClarification response: {clarification_response}"

    warnings: list[str] = []

    # 1. Decompose
    try:
        decomposition = decompose_question(effective_question)
    except GeminiGenerationError as exc:
        logger.error("Decomposition failed: %s", exc)
        return ResearchPlan(
            research_question=research_question,
            primary_domain=Domain.INTERDISCIPLINARY,
            planning_warnings=[f"Decomposition failed: {exc}"],
        )

    # Short-circuit if clarification is needed
    if decomposition.needs_clarification and not clarification_response:
        return ResearchPlan(
            research_question=research_question,
            primary_domain=Domain.INTERDISCIPLINARY,
            needs_clarification=True,
            clarification_question=decomposition.clarification_question,
        )

    warnings.extend(decomposition.warnings)

    # 2. Classify Domain
    try:
        classification = classify_domain(effective_question, decomposition.sub_questions)
    except GeminiGenerationError as exc:
        logger.warning("Classification failed, using fallback: %s", exc)
        warnings.append(f"Classification failed: {exc}")
        classification = DomainClassification(
            primary_domain=Domain.INTERDISCIPLINARY,
            relevant_sources=[SourceProvider.ARXIV, SourceProvider.SEMANTIC_SCHOLAR, SourceProvider.WEB],
        )

    # 3. Generate Search Queries
    try:
        queries = generate_search_queries(
            effective_question,
            decomposition.sub_questions,
            classification,
            settings.max_queries_per_run,
            temperature=settings.planning_query_temperature,
        )
    except GeminiGenerationError as exc:
        logger.warning("Query generation failed: %s", exc)
        warnings.append(f"Query generation failed: {exc}")
        queries = []

    if not queries:
        warnings.append("No search queries generated; falling back to original question.")
        queries = [
            SearchQuery(
                text=research_question[:100],
                target_sources=classification.relevant_sources or [SourceProvider.WEB],
            )
        ]

    return ResearchPlan(
        research_question=research_question,
        primary_domain=classification.primary_domain,
        secondary_domains=classification.secondary_domains,
        sub_questions=decomposition.sub_questions,
        search_queries=queries,
        selected_sources=classification.relevant_sources,
        document_types=classification.suggested_document_types,
        planning_warnings=warnings,
        needs_clarification=False,
    )
