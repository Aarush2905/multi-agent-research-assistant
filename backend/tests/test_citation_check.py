from app.models import Citation, ReportSection, ReportSummary, ResearchReport, Source, SourceProvider
from app.stage7_validation import check_citations


def _source(source_id: str) -> Source:
    return Source(source_id=source_id, title="Title", provider=SourceProvider.ARXIV)


def test_flags_citation_pointing_to_unknown_source():
    report = ResearchReport(
        title="T",
        research_question="Q",
        executive_summary=ReportSummary(text="summary", citation_ids=["C1"]),
        sections=[ReportSection(heading="H", body="B", citation_ids=["C1"])],
        citations=[Citation(citation_id="C1", source_id="missing-source")],
    )
    issues = check_citations(report, sources=[_source("real-source")])
    assert any("not among the retrieved sources" in i.description for i in issues)


def test_flags_section_with_no_citations():
    report = ResearchReport(
        title="T",
        research_question="Q",
        executive_summary=ReportSummary(text="summary"),
        sections=[ReportSection(heading="Uncited section", body="B", citation_ids=[])],
    )
    issues = check_citations(report, sources=[])
    assert any("makes claims with no citations" in i.description for i in issues)


def test_flags_citation_id_used_but_never_defined():
    report = ResearchReport(
        title="T",
        research_question="Q",
        executive_summary=ReportSummary(text="summary"),
        sections=[ReportSection(heading="H", body="B", citation_ids=["C99"])],
        citations=[],
    )
    issues = check_citations(report, sources=[])
    assert any("never defined" in i.description for i in issues)


def test_valid_report_has_no_errors():
    report = ResearchReport(
        title="T",
        research_question="Q",
        executive_summary=ReportSummary(text="summary", citation_ids=["C1"]),
        sections=[ReportSection(heading="H", body="B", citation_ids=["C1"])],
        citations=[Citation(citation_id="C1", source_id="real-source")],
    )
    issues = check_citations(report, sources=[_source("real-source")])
    assert all(i.severity != "error" for i in issues)
