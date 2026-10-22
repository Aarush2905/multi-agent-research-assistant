"""Stage 2: Discovery.

Executes search queries across scientific repositories (arXiv, PubMed, Semantic Scholar),
patents (Google Patents via web search), and general web search (Tavily). Normalizes,
deduplicates, and ranks sources deterministically.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx

from app.config import Settings
from app.models import (
    DocumentType,
    PublicationStatus,
    ResearchPlan,
    Source,
    SourceProvider,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalization & Deduplication
# ---------------------------------------------------------------------------

def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.strip("/") or None


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
        if not parsed.netloc:
            return None
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/")
        return f"https://{netloc}{path}"
    except Exception:
        return None


def _dedup_key(source: Source) -> tuple[str, str] | None:
    doi = normalize_doi(source.doi)
    if doi:
        return ("doi", doi)
    if source.provider == SourceProvider.ARXIV and source.external_id:
        return ("arxiv", source.external_id)
    if source.provider == SourceProvider.SEMANTIC_SCHOLAR and source.external_id:
        return ("s2", source.external_id)
    if source.provider == SourceProvider.PUBMED and source.external_id:
        return ("pubmed", source.external_id)
    url = normalize_url(source.url)
    if url:
        return ("url", url)
    return None


def _title_year_key(source: Source) -> tuple[str, int | None] | None:
    title = normalize_title(source.title)
    if len(title) < 8:
        return None
    return (title, source.publication_year)


_PROVIDER_QUALITY_RANK = {
    "pubmed": 5,
    "semantic_scholar": 4,
    "arxiv": 3,
    "patents": 2,
    "web": 1,
}


def _merge_pair(primary: Source, secondary: Source) -> Source:
    merged = primary.model_copy(deep=True)
    merged.abstract = primary.abstract or secondary.abstract
    merged.doi = primary.doi or secondary.doi
    merged.venue = primary.venue or secondary.venue
    merged.publication_year = primary.publication_year or secondary.publication_year
    merged.publication_date = primary.publication_date or secondary.publication_date
    if not merged.authors:
        merged.authors = secondary.authors
    merged.keywords = sorted(set(primary.keywords) | set(secondary.keywords))
    merged.is_open_access = (
        primary.is_open_access if primary.is_open_access is not None else secondary.is_open_access
    )
    merged.search_queries_matched = sorted(
        set(primary.search_queries_matched) | set(secondary.search_queries_matched)
    )
    merged.alternate_ids = {**secondary.alternate_ids, **primary.alternate_ids}
    
    primary_providers = primary.metadata.get("merged_providers", [primary.provider.value])
    secondary_providers = secondary.metadata.get("merged_providers", [secondary.provider.value])
    merged.metadata = {
        **secondary.metadata,
        **primary.metadata,
        "merged_providers": sorted(set(primary_providers) | set(secondary_providers)),
    }
    merged.relevance_score = max(primary.relevance_score, secondary.relevance_score)
    return merged


def rank_sources(sources: list[Source]) -> list[Source]:
    """Rank sources by peer review status, open access, presence of abstract, and provider quality."""
    def _rank_key(s: Source):
        return (
            1 if s.publication_status == PublicationStatus.PEER_REVIEWED else 0,
            1 if s.is_open_access else 0,
            1 if (s.abstract or s.provider == SourceProvider.PUBMED) else 0,
            len(s.search_queries_matched),
            _PROVIDER_QUALITY_RANK.get(s.provider.value, 0),
            s.publication_year or 0,
        )

    return sorted(sources, key=_rank_key, reverse=True)


def merge_results(sources: list[Source], max_total: int) -> list[Source]:
    """Deduplicate and merge multiple sources pointing to the same work."""
    by_strong: dict[tuple[str, str], int] = {}
    by_title_year: dict[tuple[str, int | None], int] = {}
    ordered: list[Source] = []

    for source in sources:
        strong_key = _dedup_key(source)
        weak_key = _title_year_key(source)
        idx = by_strong.get(strong_key) if strong_key else None
        if idx is None and weak_key:
            idx = by_title_year.get(weak_key)

        if idx is not None:
            existing = ordered[idx]
            a_rank = _PROVIDER_QUALITY_RANK.get(existing.provider.value, 0)
            b_rank = _PROVIDER_QUALITY_RANK.get(source.provider.value, 0)
            primary, secondary = (existing, source) if a_rank >= b_rank else (source, existing)
            merged = _merge_pair(primary, secondary)
            ordered[idx] = merged
            if strong_key:
                by_strong[strong_key] = idx
            if weak_key:
                by_title_year[weak_key] = idx
        else:
            new_idx = len(ordered)
            ordered.append(source)
            if strong_key:
                by_strong[strong_key] = new_idx
            if weak_key:
                by_title_year[weak_key] = new_idx

    ranked = rank_sources(ordered)
    return ranked[:max_total]


merge_and_rank_sources = merge_results


# ---------------------------------------------------------------------------
# Individual Search Adapters & Shared Pacing
# ---------------------------------------------------------------------------

class AsyncPacer:
    """Enforces a minimum interval between consecutive calls to a provider."""

    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0

    async def wait(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_call = loop.time()


def _parse_retry_after(response: httpx.Response, default: float = 1.0, max_wait: float = 5.0) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            val = float(header.strip())
            return min(max(val, 0.1), max_wait)
        except (ValueError, TypeError):
            pass
    return default


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    pacer: AsyncPacer | None = None,
    max_retries: int = 1,
) -> httpx.Response:
    last_resp: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        if pacer:
            await pacer.wait()
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code in (429, 503) and attempt < max_retries:
            wait_time = _parse_retry_after(resp, default=1.0 * (attempt + 1), max_wait=5.0)
            logger.warning(
                "HTTP %d on %s; retrying in %.2fs (attempt %d/%d)",
                resp.status_code,
                url,
                wait_time,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(wait_time)
            last_resp = resp
            continue
        return resp
    return last_resp or resp


_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

async def search_arxiv(
    query: str,
    limit: int,
    client: httpx.AsyncClient,
    pacer: AsyncPacer | None = None,
) -> list[Source]:
    url = "https://export.arxiv.org/api/query"
    params = {"search_query": f"all:{query}", "start": 0, "max_results": limit}
    response = await _get_with_retry(client, url, params=params, pacer=pacer)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    sources: list[Source] = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        id_url = entry.findtext("atom:id", default="", namespaces=_ARXIV_NS)
        if not id_url:
            continue
        arxiv_id = id_url.rsplit("/", 1)[-1]
        title = (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip()
        published = entry.findtext("atom:published", default=None, namespaces=_ARXIV_NS)
        authors = [
            (a.findtext("atom:name", default="", namespaces=_ARXIV_NS) or "").strip()
            for a in entry.findall("atom:author", _ARXIV_NS)
        ]
        doi = entry.findtext("arxiv:doi", default=None, namespaces=_ARXIV_NS)

        pdf_url = None
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href")

        year = int(published[:4]) if published and len(published) >= 4 and published[:4].isdigit() else None

        sources.append(
            Source(
                source_id=f"arxiv:{arxiv_id}",
                title=title,
                authors=[a for a in authors if a],
                abstract=summary or None,
                publication_year=year,
                publication_date=published,
                source_type=DocumentType.PREPRINT,
                provider=SourceProvider.ARXIV,
                url=id_url,
                doi=doi,
                external_id=arxiv_id,
                document_type=DocumentType.PREPRINT,
                publication_status=PublicationStatus.PREPRINT_NOT_REVIEWED,
                is_open_access=True,
                metadata={"pdf_url": pdf_url} if pdf_url else {},
                search_queries_matched=[query],
                alternate_ids={"arxiv": arxiv_id},
            )
        )
    return sources


_PUBMED_STOP_WORDS = {
    "and", "or", "in", "the", "of", "for", "with", "to", "a", "an", "on", "by",
    "from", "at", "as", "is", "are", "that", "this", "these", "those", "how",
    "what", "which", "into", "over", "between", "through", "after", "before",
    "using", "based", "novel", "recent", "study", "studies", "analysis", "evaluation",
    "system", "systems", "approach", "approaches", "comparative", "overview",
}


def _simplify_pubmed_query(query: str, max_words: int = 5) -> str:
    cleaned = re.sub(r"[^\w\s-]", " ", query).replace("-", " ").lower()
    tokens = [w for w in cleaned.split() if w and w not in _PUBMED_STOP_WORDS and len(w) > 2]
    seen = set()
    selected = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            selected.append(t)
        if len(selected) >= max_words:
            break
    return " ".join(selected)


async def search_pubmed(
    query: str,
    limit: int,
    client: httpx.AsyncClient,
    api_key: str | None = None,
    pacer: AsyncPacer | None = None,
) -> list[Source]:
    esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esummary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    params: dict[str, Any] = {"db": "pubmed", "term": query, "retmax": limit, "retmode": "json"}
    if api_key:
        params["api_key"] = api_key

    search_resp = await _get_with_retry(client, esearch_url, params=params, pacer=pacer)
    search_resp.raise_for_status()
    pmids = list((search_resp.json().get("esearchresult") or {}).get("idlist") or [])

    # One deduplicated low-yield fallback attempt if fewer than 5 results
    if len(pmids) < 5:
        simplified = _simplify_pubmed_query(query)
        if simplified and simplified != query.lower().strip():
            logger.info(
                "PubMed query '%s' yielded %d results; retrying with simplified keywords '%s'",
                query,
                len(pmids),
                simplified,
            )
            fallback_params = dict(params)
            fallback_params["term"] = simplified
            fallback_resp = await _get_with_retry(client, esearch_url, params=fallback_params, pacer=pacer)
            if fallback_resp.status_code == 200:
                fallback_pmids = (fallback_resp.json().get("esearchresult") or {}).get("idlist") or []
                seen_pmids = set(pmids)
                for p in fallback_pmids:
                    if p not in seen_pmids:
                        pmids.append(p)
                        seen_pmids.add(p)
                    if len(pmids) >= limit:
                        break

    if not pmids:
        return []

    sum_params: dict[str, Any] = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    if api_key:
        sum_params["api_key"] = api_key

    sum_resp = await _get_with_retry(client, esummary_url, params=sum_params, pacer=pacer)
    sum_resp.raise_for_status()
    result_block = sum_resp.json().get("result") or {}

    sources: list[Source] = []
    for pmid in result_block.get("uids", pmids):
        doc = result_block.get(pmid)
        if not doc or doc.get("error"):
            continue
        title = doc.get("title") or "Untitled"
        authors = [a.get("name", "") for a in (doc.get("authors") or []) if a.get("name")]
        pub_date = doc.get("pubdate") or doc.get("sortpubdate")
        year = None
        if pub_date:
            for token in pub_date.replace("-", " ").split():
                if token.isdigit() and len(token) == 4:
                    year = int(token)
                    break
        doi = next((a.get("value") for a in (doc.get("articleids") or []) if a.get("idtype") == "doi"), None)
        pub_types = doc.get("pubtype") or []
        is_preprint = any("preprint" in t.lower() for t in pub_types)

        sources.append(
            Source(
                source_id=f"pubmed:{pmid}",
                title=title,
                authors=authors,
                publication_year=year,
                publication_date=pub_date,
                source_type=DocumentType.PREPRINT if is_preprint else DocumentType.JOURNAL_ARTICLE,
                provider=SourceProvider.PUBMED,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                doi=doi,
                external_id=pmid,
                venue=doc.get("fulljournalname") or doc.get("source"),
                document_type=DocumentType.PREPRINT if is_preprint else DocumentType.JOURNAL_ARTICLE,
                publication_status=(
                    PublicationStatus.PREPRINT_NOT_REVIEWED if is_preprint else PublicationStatus.PEER_REVIEWED
                ),
                metadata={"pubtypes": pub_types},
                search_queries_matched=[query],
                alternate_ids={"pubmed": pmid, **({"doi": doi} if doi else {})},
            )
        )
    return sources


async def search_semantic_scholar(
    query: str,
    limit: int,
    client: httpx.AsyncClient,
    api_key: str | None = None,
    pacer: AsyncPacer | None = None,
) -> list[Source]:
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,abstract,authors,year,publicationDate,venue,externalIds,isOpenAccess,openAccessPdf,publicationTypes,citationCount"
    params = {"query": query, "limit": limit, "fields": fields}
    headers = {"x-api-key": api_key} if api_key else {}

    response = await _get_with_retry(client, url, params=params, headers=headers, pacer=pacer)
    if response.status_code == 429:
        logger.warning("Semantic Scholar rate limited (429) after retry.")
        return []
    response.raise_for_status()

    papers = response.json().get("data") or []
    sources: list[Source] = []
    for paper in papers:
        paper_id = paper.get("paperId")
        if not paper_id:
            continue
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        pub_types = paper.get("publicationTypes") or []
        doc_type = DocumentType.CONFERENCE_PAPER if "Conference" in pub_types else DocumentType.JOURNAL_ARTICLE
        open_access_pdf = (paper.get("openAccessPdf") or {}).get("url")

        sources.append(
            Source(
                source_id=f"s2:{paper_id}",
                title=paper.get("title") or "Untitled",
                authors=[a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")],
                abstract=paper.get("abstract"),
                publication_year=paper.get("year"),
                publication_date=paper.get("publicationDate"),
                source_type=doc_type,
                provider=SourceProvider.SEMANTIC_SCHOLAR,
                url=f"https://www.semanticscholar.org/paper/{paper_id}",
                doi=doi,
                external_id=paper_id,
                venue=paper.get("venue") or None,
                document_type=doc_type,
                publication_status=PublicationStatus.PEER_REVIEWED,
                is_open_access=paper.get("isOpenAccess"),
                metadata={"citation_count": paper.get("citationCount"), "pdf_url": open_access_pdf},
                search_queries_matched=[query],
                alternate_ids={"semantic_scholar": paper_id, **({"doi": doi} if doi else {})},
            )
        )
    return sources


async def search_web(
    query: str,
    limit: int,
    client: httpx.AsyncClient,
    api_key: str | None,
    provider: SourceProvider = SourceProvider.WEB,
    semaphore: asyncio.Semaphore | None = None,
) -> list[Source]:
    if not api_key:
        return []

    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "search_depth": "advanced",
        "topic": "general",
        "include_answer": False,
    }
    if semaphore:
        async with semaphore:
            response = await client.post(url, json=payload)
    else:
        response = await client.post(url, json=payload)
    response.raise_for_status()

    results = response.json().get("results") or []
    sources: list[Source] = []
    for item in results:
        target_url = item.get("url")
        if not target_url:
            continue
        is_patent = provider == SourceProvider.PATENTS
        doc_type = DocumentType.PATENT if is_patent else DocumentType.WEBPAGE
        sources.append(
            Source(
                source_id=f"{provider.value}:{target_url}",
                title=item.get("title") or target_url,
                abstract=item.get("content"),
                source_type=doc_type,
                provider=provider,
                url=target_url,
                document_type=doc_type,
                publication_status=PublicationStatus.UNKNOWN,
                relevance_score=float(item.get("score") or 0.0),
                metadata={"tavily_raw_score": item.get("score")},
                search_queries_matched=[query],
            )
        )
    return sources


# ---------------------------------------------------------------------------
# Stage 2 Orchestrator
# ---------------------------------------------------------------------------

async def run_discovery(plan: ResearchPlan, settings: Settings) -> tuple[list[Source], dict[str, str]]:
    """Execute all search queries in the research plan concurrently with shared per-provider pacing."""
    collected: list[Source] = []
    provider_errors: dict[str, str] = {}

    timeout = httpx.Timeout(settings.http_timeout_seconds)
    headers = {"User-Agent": "ResearchAssistant/1.0 (academic research agent)"}

    # Shared per-provider request pacers
    pubmed_pacer = AsyncPacer(min_interval_seconds=0.1 if settings.ncbi_api_key else 0.35)
    arxiv_pacer = AsyncPacer(min_interval_seconds=3.0)
    s2_pacer = AsyncPacer(min_interval_seconds=0.1 if settings.semantic_scholar_api_key else 1.0)
    web_semaphore = asyncio.Semaphore(4)

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        tasks = []

        for sq in plan.search_queries[: settings.max_queries_per_run]:
            targets = sq.target_sources or plan.selected_sources or [SourceProvider.ARXIV, SourceProvider.WEB]
            for provider in targets:
                if provider == SourceProvider.ARXIV:
                    tasks.append((SourceProvider.ARXIV, sq.text, search_arxiv(sq.text, settings.max_results_per_query, client, arxiv_pacer)))
                elif provider == SourceProvider.PUBMED:
                    tasks.append((SourceProvider.PUBMED, sq.text, search_pubmed(sq.text, settings.max_results_per_query, client, settings.ncbi_api_key, pubmed_pacer)))
                elif provider == SourceProvider.SEMANTIC_SCHOLAR:
                    tasks.append((SourceProvider.SEMANTIC_SCHOLAR, sq.text, search_semantic_scholar(sq.text, settings.max_results_per_query, client, settings.semantic_scholar_api_key, s2_pacer)))
                elif provider == SourceProvider.PATENTS:
                    patent_q = f"{sq.text} patent"
                    tasks.append((SourceProvider.PATENTS, sq.text, search_web(patent_q, settings.max_results_per_query, client, settings.tavily_api_key, SourceProvider.PATENTS, web_semaphore)))
                elif provider == SourceProvider.WEB:
                    tasks.append((SourceProvider.WEB, sq.text, search_web(sq.text, settings.max_results_per_query, client, settings.tavily_api_key, SourceProvider.WEB, web_semaphore)))

        results = await asyncio.gather(*(t[2] for t in tasks), return_exceptions=True)

        for (provider, q_text, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.warning("Search failed for %s query '%s': %s", provider.value, q_text, result)
                provider_errors[provider.value] = str(result)
            elif isinstance(result, list):
                collected.extend(result)

    final_sources = merge_results(collected, settings.max_total_sources)
    return final_sources, provider_errors
