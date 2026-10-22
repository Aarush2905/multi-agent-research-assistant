"""Deterministic PDF export of research reports using ReportLab."""

from __future__ import annotations

import io
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models import ResearchReport, Source


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_report_pdf(report: ResearchReport, sources: list[Source]) -> bytes:
    """Render a completed ResearchReport into publication-quality PDF bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )
    styles = getSampleStyleSheet()
    heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], spaceBefore=14)
    body_style = styles["BodyText"]

    sources_by_id = {s.source_id: s for s in sources}
    story = []

    # Title & Question
    story.append(Paragraph(_escape(report.title), styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(f"<i>{_escape(report.research_question)}</i>", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    # Executive Summary
    story.append(Paragraph("Executive Summary", heading_style))
    story.append(Paragraph(_escape(report.executive_summary.text), body_style))
    if report.executive_summary.citation_ids:
        story.append(
            Paragraph(f"<i>Citations: {', '.join(report.executive_summary.citation_ids)}</i>", styles["Normal"])
        )
    story.append(Spacer(1, 0.15 * inch))

    # Sections
    for section in report.sections:
        story.append(Paragraph(_escape(section.heading), heading_style))
        story.append(Paragraph(_escape(section.body), body_style))
        if section.citation_ids:
            story.append(
                Paragraph(f"<i>Citations: {', '.join(section.citation_ids)}</i>", styles["Normal"])
            )
        story.append(Spacer(1, 0.1 * inch))

    # Limitations
    if report.limitations:
        story.append(Paragraph("Limitations", heading_style))
        for item in report.limitations:
            story.append(Paragraph(f"- {_escape(item)}", body_style))

    # Research Gaps
    if report.research_gaps:
        story.append(Paragraph("Research Gaps", heading_style))
        for item in report.research_gaps:
            story.append(Paragraph(f"- {_escape(item)}", body_style))

    # References
    if report.citations:
        story.append(Paragraph("References", heading_style))
        for citation in report.citations:
            source = sources_by_id.get(citation.source_id)
            if source:
                authors = ", ".join(source.authors[:3]) or "Unknown authors"
                year = source.publication_year or "n.d."
                line = f"[{citation.citation_id}] {authors} ({year}). {source.title}. {source.url or ''}"
            else:
                line = f"[{citation.citation_id}] {citation.source_id}"
            story.append(Paragraph(_escape(line), body_style))

    doc.build(story)
    return buffer.getvalue()
