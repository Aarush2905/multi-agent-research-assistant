"""Unified data models for the Multi-Agent Research Assistant.

Includes domain enums, research plan structures, sources, extracted evidence,
synthesis reports, validation results, and pipeline state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StrEnum(str, Enum):
    """String enum compatible across Python versions."""

    def __str__(self) -> str:
        return str(self.value)


class SourceProvider(StrEnum):
    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    PUBMED = "pubmed"
    PATENTS = "patents"
    WEB = "web"


class Domain(StrEnum):
    COMPUTER_SCIENCE_AI = "computer_science_ai"
    MEDICINE_BIOMEDICAL = "medicine_biomedical"
    BIOLOGY = "biology"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    MATERIALS_SCIENCE = "materials_science"
    ECONOMICS_FINANCE = "economics_finance"
    BUSINESS_TECHNOLOGY = "business_technology"
    LAW_SOCIAL_SCIENCES = "law_social_sciences"
    INTERDISCIPLINARY = "interdisciplinary"


class DocumentType(StrEnum):
    JOURNAL_ARTICLE = "journal_article"
    PREPRINT = "preprint"
    CONFERENCE_PAPER = "conference_paper"
    PATENT = "patent"
    PATENT_APPLICATION = "patent_application"
    COMPANY_REPORT = "company_report"
    NEWS = "news"
    GOVERNMENT_PUBLICATION = "government_publication"
    TECHNICAL_DOCUMENTATION = "technical_documentation"
    WEBPAGE = "webpage"
    UNKNOWN = "unknown"


class PublicationStatus(StrEnum):
    PEER_REVIEWED = "peer_reviewed"
    PREPRINT_NOT_REVIEWED = "preprint_not_reviewed"
    UNKNOWN = "unknown"


class RetrievalStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED_PAYWALL = "failed_paywall"
    FAILED_NOT_FOUND = "failed_not_found"
    FAILED_TIMEOUT = "failed_timeout"
    FAILED_UNSUPPORTED_FORMAT = "failed_unsupported_format"


class RunStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    DISCOVERY = "discovery"
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"
    CROSS_ANALYSIS = "cross_analysis"
    SYNTHESIS = "synthesis"
    VALIDATION = "validation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Stage 1: Planning Models
# ---------------------------------------------------------------------------

class SubQuestion(BaseModel):
    text: str
    rationale: str = ""


class DomainClassification(BaseModel):
    primary_domain: Domain
    secondary_domains: list[Domain] = Field(default_factory=list)
    justification: str = ""
    relevant_sources: list[SourceProvider] = Field(default_factory=list)
    suggested_document_types: list[DocumentType] = Field(default_factory=list)


class SearchQuery(BaseModel):
    text: str
    target_sources: list[SourceProvider] = Field(default_factory=list)
    originating_subquestion: str | None = None


class ResearchPlan(BaseModel):
    research_question: str
    primary_domain: Domain = Domain.INTERDISCIPLINARY
    secondary_domains: list[Domain] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    search_queries: list[SearchQuery] = Field(default_factory=list)
    selected_sources: list[SourceProvider] = Field(default_factory=list)
    document_types: list[DocumentType] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    planning_warnings: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None


# ---------------------------------------------------------------------------
# Stage 2 & 3: Sources & Retrieved Documents
# ---------------------------------------------------------------------------

class Source(BaseModel):
    source_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    source_type: DocumentType = DocumentType.UNKNOWN
    provider: SourceProvider
    url: str | None = None
    doi: str | None = None
    external_id: str | None = None
    venue: str | None = None
    keywords: list[str] = Field(default_factory=list)
    document_type: DocumentType = DocumentType.UNKNOWN
    publication_status: PublicationStatus = PublicationStatus.UNKNOWN
    is_open_access: bool | None = None
    retrieval_status: RetrievalStatus = RetrievalStatus.NOT_ATTEMPTED
    retrieval_error: str | None = None
    relevance_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    search_queries_matched: list[str] = Field(default_factory=list)
    alternate_ids: dict[str, str] = Field(default_factory=dict)


class RetrievedDocument(BaseModel):
    source_id: str
    full_text: str | None = None
    text_excerpt: str | None = None
    retrieval_status: RetrievalStatus = RetrievalStatus.NOT_ATTEMPTED
    retrieval_error: str | None = None
    content_format: str | None = None
    char_count: int = 0


# ---------------------------------------------------------------------------
# Stage 4 & 5: Evidence & Cross-Source Analysis
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    text: str
    supporting_quote: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class Metric(BaseModel):
    name: str
    value: str
    unit: str | None = None
    context: str | None = None


class SourceAnalysis(BaseModel):
    source_id: str
    key_findings: list[Claim] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    relevance_to_subquestions: dict[str, str] = Field(default_factory=dict)
    analysis_warnings: list[str] = Field(default_factory=list)


class Agreement(BaseModel):
    topic: str
    source_ids: list[str] = Field(default_factory=list)
    summary: str


class Disagreement(BaseModel):
    topic: str
    source_ids: list[str] = Field(default_factory=list)
    summary: str


class ResearchGap(BaseModel):
    description: str
    related_subquestion: str | None = None


class CrossSourceAnalysis(BaseModel):
    agreements: list[Agreement] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)
    research_gaps: list[ResearchGap] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 6 & 7: Synthesis Report & Validation
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    citation_id: str
    source_id: str


class ReportSection(BaseModel):
    heading: str
    body: str
    citation_ids: list[str] = Field(default_factory=list)


class ReportSummary(BaseModel):
    text: str
    citation_ids: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    title: str
    research_question: str
    executive_summary: ReportSummary
    sections: list[ReportSection] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationIssue(BaseModel):
    severity: str  # "error" | "warning"
    description: str
    section_heading: str | None = None
    citation_id: str | None = None


class ValidationResult(BaseModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    unsupported_citation_ids: list[str] = Field(default_factory=list)
    repair_attempt: int = 0


# ---------------------------------------------------------------------------
# Pipeline State & API Payloads
# ---------------------------------------------------------------------------

class FollowUpExchange(BaseModel):
    question: str
    answer: str
    citation_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResearchState(TypedDict, total=False):
    run_id: str
    research_question: str
    clarification_response: str | None
    status: RunStatus
    errors: list[str]
    plan: ResearchPlan | None
    sources: list[Source]
    retrieved_documents: list[RetrievedDocument]
    source_analyses: list[SourceAnalysis]
    cross_source_analysis: CrossSourceAnalysis | None
    report: ResearchReport | None
    validation: ValidationResult | None
    validation_attempts: int
    stage_warnings: dict[str, list[str]]
    provider_errors: dict[str, str]


def new_state(run_id: str, research_question: str) -> ResearchState:
    return ResearchState(
        run_id=run_id,
        research_question=research_question,
        clarification_response=None,
        status=RunStatus.PENDING,
        errors=[],
        plan=None,
        sources=[],
        retrieved_documents=[],
        source_analyses=[],
        cross_source_analysis=None,
        report=None,
        validation=None,
        validation_attempts=0,
        stage_warnings={},
        provider_errors={},
    )


def serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert state objects to JSON-serializable dictionaries."""
    out: dict[str, Any] = {}
    for key, value in state.items():
        if hasattr(value, "model_dump"):
            out[key] = value.model_dump(mode="json")
        elif isinstance(value, list) and value and hasattr(value[0], "model_dump"):
            out[key] = [v.model_dump(mode="json") for v in value]
        else:
            out[key] = value
    return out
