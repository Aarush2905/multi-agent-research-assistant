"""Stage 3: Retrieval.

Fetches full-text content (PDF / HTML) for discovered sources using:
- NCBI E-utilities (efetch) for PubMed records (avoids 403 bot blocks and retrieves full structured abstracts)
- PyMuPDF (fitz) and BeautifulSoup for web and preprint PDFs/HTML
- Automated abstract fallback for paywalled or restricted sources
"""

from __future__ import annotations

import asyncio
import io
import logging
from xml.etree import ElementTree as ET

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.models import RetrievalStatus, RetrievedDocument, Source, SourceProvider

logger = logging.getLogger(__name__)

MAX_CHARS = 60_000
MAX_CONCURRENCY = 6


def extract_html_text(html: str) -> str:
    """Extract clean body text from HTML, stripping boilerplate and scripts."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:MAX_CHARS]


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF pages using PyMuPDF."""
    text_parts: list[str] = []
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text())
            if sum(len(p) for p in text_parts) >= MAX_CHARS:
                break
    return "\n".join(text_parts)[:MAX_CHARS]


async def _fetch_pubmed_batch(
    client: httpx.AsyncClient,
    sources: list[Source],
    api_key: str | None = None,
) -> dict[str, RetrievedDocument]:
    """Fetch structured abstracts in batches for all PubMed sources via NCBI's official efetch API."""
    if not sources:
        return {}

    pmid_to_source: dict[str, Source] = {}
    for s in sources:
        pmid = s.external_id or s.source_id.split(":", 1)[-1]
        pmid_to_source[pmid] = s

    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    results: dict[str, RetrievedDocument] = {}

    pmids = list(pmid_to_source.keys())
    chunk_size = 50

    for i in range(0, len(pmids), chunk_size):
        chunk = pmids[i : i + chunk_size]
        params = {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
        if api_key:
            params["api_key"] = api_key

        last_error = ""
        root: ET.Element | None = None

        for attempt in range(2):
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    last_error = "Rate limited (429) by NCBI"
                    await asyncio.sleep(1.0)
                    continue
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                break
            except Exception as exc:
                last_error = str(exc)
                logger.warning("NCBI batch efetch attempt %d failed: %s", attempt + 1, exc)
                if attempt == 0:
                    await asyncio.sleep(0.5)

        if root is not None:
            for art in root.findall(".//PubmedArticle"):
                pmid_el = art.find(".//MedlineCitation/PMID")
                art_pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None
                if not art_pmid or art_pmid not in pmid_to_source:
                    continue

                source = pmid_to_source[art_pmid]
                abstract_parts: list[str] = []
                for el in art.findall(".//AbstractText"):
                    label = el.get("Label")
                    text = "".join(el.itertext()).strip()
                    if text:
                        abstract_parts.append(f"{label}: {text}" if label else text)

                full_abstract = "\n\n".join(abstract_parts)
                if full_abstract:
                    source.abstract = full_abstract
                    results[source.source_id] = RetrievedDocument(
                        source_id=source.source_id,
                        full_text=full_abstract,
                        text_excerpt=full_abstract[:1000],
                        retrieval_status=RetrievalStatus.SUCCESS,
                        content_format="ncbi_xml",
                        char_count=len(full_abstract),
                    )

        # For any source in this chunk not successfully populated
        for pmid in chunk:
            source = pmid_to_source[pmid]
            if source.source_id not in results:
                if source.abstract:
                    results[source.source_id] = RetrievedDocument(
                        source_id=source.source_id,
                        full_text=source.abstract,
                        text_excerpt=source.abstract[:1000],
                        retrieval_status=RetrievalStatus.SUCCESS,
                        content_format="abstract_fallback",
                        char_count=len(source.abstract),
                    )
                else:
                    results[source.source_id] = RetrievedDocument(
                        source_id=source.source_id,
                        retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
                        retrieval_error=last_error or "No abstract published in PubMed for this record.",
                    )

    return results


async def _fetch_single_source(
    client: httpx.AsyncClient,
    source: Source,
    semaphore: asyncio.Semaphore,
    settings: Settings,
) -> RetrievedDocument:
    # Use official NCBI API for PubMed to avoid 403 anti-bot blocks
    if source.provider == SourceProvider.PUBMED:
        batch = await _fetch_pubmed_batch(client, [source], settings.ncbi_api_key)
        return batch.get(source.source_id) or RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
            retrieval_error="PubMed retrieval failed.",
        )

    url = source.metadata.get("pdf_url") or source.url
    if not url:
        return RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
            retrieval_error="No URL available for this source.",
        )

    async with semaphore:
        try:
            response = await client.get(url, follow_redirects=True)
        except httpx.TimeoutException:
            return RetrievedDocument(
                source_id=source.source_id,
                retrieval_status=RetrievalStatus.FAILED_TIMEOUT,
                retrieval_error="Connection timed out while fetching document.",
            )
        except httpx.HTTPError as exc:
            err_str = str(exc)
            if "CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str:
                err_msg = "SSL certificate validation failed on host server"
            elif "ConnectError" in type(exc).__name__:
                err_msg = f"Connection failed to host server: {err_str}"
            else:
                err_msg = f"Network error: {err_str}"
            return RetrievedDocument(
                source_id=source.source_id,
                retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
                retrieval_error=err_msg,
            )

    if response.status_code in (402, 403):
        return RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_PAYWALL,
            retrieval_error=f"Paywall or restricted access (HTTP {response.status_code})",
        )
    if response.status_code >= 400:
        if response.status_code == 404:
            err_msg = "Document not found on server (HTTP 404)"
        elif response.status_code == 400:
            err_msg = "Automated scraper rejected by site (HTTP 400)"
        elif response.status_code == 429:
            err_msg = "Rate limit exceeded on host server (HTTP 429)"
        else:
            err_msg = f"Server returned HTTP error {response.status_code}"
        return RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
            retrieval_error=err_msg,
        )

    content_type = response.headers.get("content-type", "").lower()

    try:
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            text = extract_pdf_text(response.content)
            content_format = "pdf"
        elif "html" in content_type or not content_type:
            text = extract_html_text(response.text)
            content_format = "html"
        else:
            return RetrievedDocument(
                source_id=source.source_id,
                retrieval_status=RetrievalStatus.FAILED_UNSUPPORTED_FORMAT,
                retrieval_error=f"Unsupported content-type: {content_type}",
            )
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", source.source_id, exc)
        return RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_UNSUPPORTED_FORMAT,
            retrieval_error=f"Extraction failed: {exc}",
        )

    if not text.strip():
        if source.abstract:
            return RetrievedDocument(
                source_id=source.source_id,
                full_text=source.abstract,
                text_excerpt=source.abstract[:1000],
                retrieval_status=RetrievalStatus.PARTIAL,
                content_format="abstract_fallback",
                char_count=len(source.abstract),
            )
        return RetrievedDocument(
            source_id=source.source_id,
            retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
            retrieval_error="Extracted text is empty.",
        )

    return RetrievedDocument(
        source_id=source.source_id,
        full_text=text,
        text_excerpt=text[:1000],
        retrieval_status=RetrievalStatus.SUCCESS,
        content_format=content_format,
        char_count=len(text),
    )


async def run_retrieval(sources: list[Source], settings: Settings) -> list[RetrievedDocument]:
    """Fetch and extract documents for all discovered sources, batching PubMed requests."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    timeout = httpx.Timeout(settings.http_timeout_seconds)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    }

    pubmed_sources = [s for s in sources if s.provider == SourceProvider.PUBMED]
    other_sources = [s for s in sources if s.provider != SourceProvider.PUBMED]

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        if other_sources:
            pubmed_docs_map, other_docs = await asyncio.gather(
                _fetch_pubmed_batch(client, pubmed_sources, settings.ncbi_api_key),
                asyncio.gather(*[_fetch_single_source(client, s, semaphore, settings) for s in other_sources]),
            )
        else:
            pubmed_docs_map = await _fetch_pubmed_batch(client, pubmed_sources, settings.ncbi_api_key)
            other_docs = []

    docs_by_id = dict(pubmed_docs_map)
    for d in other_docs:
        docs_by_id[d.source_id] = d

    # Preserve exact order of input sources
    ordered_documents = [
        docs_by_id.get(
            s.source_id,
            RetrievedDocument(
                source_id=s.source_id,
                retrieval_status=RetrievalStatus.FAILED_NOT_FOUND,
                retrieval_error="Document retrieval was not completed.",
            ),
        )
        for s in sources
    ]

    # Reflect retrieval status and error onto sources
    for source in sources:
        doc = docs_by_id.get(source.source_id)
        if doc:
            source.retrieval_status = doc.retrieval_status
            source.retrieval_error = doc.retrieval_error

    return ordered_documents
