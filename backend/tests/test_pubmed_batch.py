import pytest
import httpx
from app.config import Settings
from app.models import RetrievalStatus, Source, SourceProvider
from app.stage3_retrieval import _fetch_pubmed_batch, run_retrieval


_MOCK_NCBI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111111</PMID>
      <Article>
        <ArticleTitle>Paper 1</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background info.</AbstractText>
          <AbstractText Label="RESULTS">Important results found.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>222222</PMID>
      <Article>
        <ArticleTitle>Paper 2</ArticleTitle>
        <Abstract>
          <AbstractText>Unlabeled single abstract paragraph.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


@pytest.mark.asyncio
async def test_fetch_pubmed_batch_parses_multiple_articles():
    s1 = Source(source_id="pubmed:111111", external_id="111111", title="Paper 1", provider=SourceProvider.PUBMED)
    s2 = Source(source_id="pubmed:222222", external_id="222222", title="Paper 2", provider=SourceProvider.PUBMED)

    def mock_handler(request: httpx.Request):
        return httpx.Response(200, text=_MOCK_NCBI_XML)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        results = await _fetch_pubmed_batch(client, [s1, s2])

    assert len(results) == 2
    assert results["pubmed:111111"].retrieval_status == RetrievalStatus.SUCCESS
    assert "BACKGROUND: Background info." in results["pubmed:111111"].full_text
    assert "RESULTS: Important results found." in results["pubmed:111111"].full_text

    assert results["pubmed:222222"].retrieval_status == RetrievalStatus.SUCCESS
    assert results["pubmed:222222"].full_text == "Unlabeled single abstract paragraph."


@pytest.mark.asyncio
async def test_run_retrieval_preserves_order():
    s_pm = Source(source_id="pubmed:111111", external_id="111111", title="Paper 1", provider=SourceProvider.PUBMED)
    s_arxiv = Source(
        source_id="arxiv:2401.0001",
        external_id="2401.0001",
        title="Arxiv Paper",
        provider=SourceProvider.ARXIV,
        url="https://arxiv.org/abs/2401.0001",
        abstract="Arxiv abstract",
    )

    def mock_handler(request: httpx.Request):
        if "efetch" in str(request.url):
            return httpx.Response(200, text=_MOCK_NCBI_XML)
        return httpx.Response(200, text="<html><body>arXiv HTML body text</body></html>", headers={"content-type": "text/html"})

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(gemini_api_key="test-key")

    # Pass in [s_arxiv, s_pm] - retrieval must return them in that exact order
    import app.stage3_retrieval
    original_client = httpx.AsyncClient

    class CustomClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    # Temporarily patch AsyncClient
    import unittest.mock
    with unittest.mock.patch("httpx.AsyncClient", CustomClient):
        docs = await run_retrieval([s_arxiv, s_pm], settings)

    assert len(docs) == 2
    assert docs[0].source_id == "arxiv:2401.0001"
    assert docs[1].source_id == "pubmed:111111"
    assert docs[0].retrieval_status == RetrievalStatus.SUCCESS
    assert docs[1].retrieval_status == RetrievalStatus.SUCCESS
