import asyncio
import time
import httpx
import pytest
from app.config import Settings
from app.models import ResearchPlan, SearchQuery, Source, SourceProvider
from app.stage2_discovery import (
    AsyncPacer,
    _get_with_retry,
    _parse_retry_after,
    _simplify_pubmed_query,
    run_discovery,
    search_pubmed,
)


@pytest.mark.asyncio
async def test_async_pacer_enforces_minimum_spacing():
    interval = 0.08
    pacer = AsyncPacer(min_interval_seconds=interval)

    timestamps: list[float] = []

    async def worker():
        await pacer.wait()
        timestamps.append(time.monotonic())

    # Fire 3 workers concurrently
    t0 = time.monotonic()
    await asyncio.gather(worker(), worker(), worker())
    total_elapsed = time.monotonic() - t0

    assert len(timestamps) == 3
    # First call is immediate, second waits ~interval, third waits ~interval -> total >= 2 * interval
    assert total_elapsed >= (2 * interval) * 0.95
    assert timestamps[1] - timestamps[0] >= interval * 0.9
    assert timestamps[2] - timestamps[1] >= interval * 0.9


@pytest.mark.asyncio
async def test_parse_retry_after_header_and_bounds():
    # Integer header
    r1 = httpx.Response(429, headers={"Retry-After": "2"})
    assert _parse_retry_after(r1) == 2.0

    # Float header
    r2 = httpx.Response(429, headers={"Retry-After": "0.5"})
    assert _parse_retry_after(r2) == 0.5

    # Excessive header gets bounded by max_wait
    r3 = httpx.Response(429, headers={"Retry-After": "120"})
    assert _parse_retry_after(r3, max_wait=5.0) == 5.0

    # Missing header uses default
    r4 = httpx.Response(429)
    assert _parse_retry_after(r4, default=1.5) == 1.5

    # Invalid header uses default
    r5 = httpx.Response(429, headers={"Retry-After": "not-a-number"})
    assert _parse_retry_after(r5, default=1.0) == 1.0


@pytest.mark.asyncio
async def test_get_with_retry_succeeds_after_429():
    calls = 0

    def mock_handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.02"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await _get_with_retry(client, "https://api.test/resource", max_retries=1)

    assert resp.status_code == 200
    assert calls == 2


@pytest.mark.asyncio
async def test_get_with_retry_bounds_at_max_retries():
    calls = 0

    def mock_handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0.01"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await _get_with_retry(client, "https://api.test/resource", max_retries=2)

    assert resp.status_code == 429
    assert calls == 3  # initial attempt + 2 retries


@pytest.mark.asyncio
async def test_pubmed_low_yield_fallback_deduplicates_and_preserves():
    search_queries_received: list[str] = []

    _MOCK_ESUMMARY_XML = {
        "result": {
            "uids": ["101", "102", "103"],
            "101": {"title": "Initial Paper 1", "pubdate": "2024"},
            "102": {"title": "Initial Paper 2", "pubdate": "2024"},
            "103": {"title": "Fallback Paper 3", "pubdate": "2024"},
        }
    }

    def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if "esearch.fcgi" in url_str:
            term = request.url.params.get("term", "")
            search_queries_received.append(term)
            if "simplified" in term or len(term.split()) <= 5:
                # Fallback query returns overlap ("102") plus new paper ("103")
                return httpx.Response(200, json={"esearchresult": {"idlist": ["102", "103"]}})
            # Initial verbose query returns only 2 papers (< 5 threshold)
            return httpx.Response(200, json={"esearchresult": {"idlist": ["101", "102"]}})
        elif "esummary.fcgi" in url_str:
            return httpx.Response(200, json=_MOCK_ESUMMARY_XML)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Long query with 8 words
        long_query = "Brain computer interfaces neural signal decoding algorithms electrode biocompatibility"
        sources = await search_pubmed(long_query, limit=10, client=client)

    # Must trigger fallback because initial result count (2) was < 5
    assert len(search_queries_received) == 2
    # Result must preserve initial 2 papers and deduplicate the overlapping paper "102"
    source_ids = [s.source_id for s in sources]
    assert source_ids == ["pubmed:101", "pubmed:102", "pubmed:103"]


@pytest.mark.asyncio
async def test_pubmed_no_fallback_when_yield_sufficient():
    search_queries_received: list[str] = []

    _MOCK_ESUMMARY_XML = {
        "result": {
            "uids": [str(i) for i in range(1, 7)],
            **{str(i): {"title": f"Paper {i}", "pubdate": "2024"} for i in range(1, 7)},
        }
    }

    def mock_handler(request: httpx.Request):
        if "esearch.fcgi" in str(request.url):
            term = request.url.params.get("term", "")
            search_queries_received.append(term)
            # Returns 6 papers (>= 5 threshold)
            return httpx.Response(200, json={"esearchresult": {"idlist": [str(i) for i in range(1, 7)]}})
        elif "esummary.fcgi" in str(request.url):
            return httpx.Response(200, json=_MOCK_ESUMMARY_XML)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        sources = await search_pubmed("brain computer interfaces neural decoding", limit=10, client=client)

    # Only 1 search query should be made; fallback should NOT be triggered
    assert len(search_queries_received) == 1
    assert len(sources) == 6


@pytest.mark.asyncio
async def test_preservation_of_successful_results_when_one_provider_fails():
    plan = ResearchPlan(
        research_question="Brain computer interfaces",
        search_queries=[
            SearchQuery(text="neural decoding", target_sources=[SourceProvider.ARXIV]),
            SearchQuery(text="neural interfaces", target_sources=[SourceProvider.SEMANTIC_SCHOLAR]),
        ],
    )

    settings = Settings(gemini_api_key="test-key")

    _MOCK_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2401.0001</id>
        <title>ArXiv Success Paper</title>
        <summary>Paper abstract.</summary>
        <published>2024-01-01</published>
      </entry>
    </feed>
    """

    def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if "arxiv.org" in url_str:
            return httpx.Response(200, text=_MOCK_ARXIV_XML)
        elif "semanticscholar.org" in url_str:
            # S2 fails with 500 error
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)

    class CustomClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    import unittest.mock
    with unittest.mock.patch("httpx.AsyncClient", CustomClient):
        sources, provider_errors = await run_discovery(plan, settings)

    # ArXiv paper must be successfully collected and preserved despite S2 failing
    assert len(sources) == 1
    assert sources[0].source_id == "arxiv:2401.0001"
    # S2 failure must be captured in provider_errors
    assert "semantic_scholar" in provider_errors
