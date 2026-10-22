from app.models import SearchQuery, SourceProvider
from app.stage1_planning import _dedup_and_limit


def test_dedup_removes_near_identical_queries():
    queries = [
        SearchQuery(text="battery chemistry comparison", target_sources=[SourceProvider.ARXIV]),
        SearchQuery(text="Battery Chemistry Comparison!", target_sources=[SourceProvider.ARXIV]),
        SearchQuery(text="manufacturing cost analysis", target_sources=[SourceProvider.WEB]),
    ]
    result = _dedup_and_limit(queries, [SourceProvider.ARXIV, SourceProvider.WEB], max_queries=10)
    assert len(result) == 2


def test_limit_enforced():
    queries = [
        SearchQuery(text=f"query number {i}", target_sources=[SourceProvider.ARXIV]) for i in range(10)
    ]
    result = _dedup_and_limit(queries, [SourceProvider.ARXIV], max_queries=3)
    assert len(result) == 3


def test_queries_targeting_unselected_sources_are_dropped():
    queries = [SearchQuery(text="some query", target_sources=[SourceProvider.PUBMED])]
    result = _dedup_and_limit(queries, [SourceProvider.ARXIV], max_queries=10)
    assert result == []


def test_simplify_pubmed_query():
    from app.stage2_discovery import _simplify_pubmed_query

    long_q = "Brain-computer interfaces: neural signal decoding algorithms, electrode biocompatibility, and clinical implants"
    simplified = _simplify_pubmed_query(long_q)
    assert simplified == "brain computer interfaces neural signal"
    assert len(simplified.split()) <= 5


def test_rank_sources_does_not_penalize_pubmed_for_missing_stage2_abstract():
    from app.models import PublicationStatus, Source
    from app.stage2_discovery import rank_sources

    arxiv_with_abstract = Source(
        source_id="arxiv:1",
        title="Neural decoding in BCIs",
        provider=SourceProvider.ARXIV,
        external_id="1",
        publication_status=PublicationStatus.PREPRINT_NOT_REVIEWED,
        is_open_access=True,
        abstract="Detailed abstract here...",
    )
    pubmed_peer_reviewed_no_abstract = Source(
        source_id="pubmed:1",
        title="Clinical neural interfaces",
        provider=SourceProvider.PUBMED,
        external_id="1",
        publication_status=PublicationStatus.PEER_REVIEWED,
        is_open_access=True,
        abstract=None,
    )
    ranked = rank_sources([arxiv_with_abstract, pubmed_peer_reviewed_no_abstract])
    # Peer-reviewed PubMed paper should rank first ahead of preprint arXiv even without abstract populated yet
    assert ranked[0].source_id == "pubmed:1"

