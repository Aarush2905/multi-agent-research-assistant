from app.models import PublicationStatus, Source, SourceProvider
from app.stage2_discovery import merge_results, normalize_doi, normalize_title, normalize_url, rank_sources


def _source(**overrides) -> Source:
    defaults = dict(
        source_id="s1",
        title="Battery chemistry comparison for electric vehicles",
        provider=SourceProvider.ARXIV,
        external_id="1234.5678",
        publication_year=2023,
    )
    defaults.update(overrides)
    return Source(**defaults)


def test_normalize_url_strips_scheme_www_trailing_slash():
    assert normalize_url("http://www.Example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/path") == "https://example.com/path"
    assert normalize_url(None) is None


def test_normalize_doi_strips_prefixes():
    assert normalize_doi("https://doi.org/10.1000/xyz123") == "10.1000/xyz123"
    assert normalize_doi("DOI:10.1000/XYZ123") == "10.1000/xyz123"


def test_normalize_title_strips_punctuation_and_case():
    assert normalize_title("Battery Chemistry: A Review!") == "battery chemistry a review"


def test_merge_deduplicates_by_doi():
    a = _source(source_id="s2:1", provider=SourceProvider.SEMANTIC_SCHOLAR, doi="10.1/ABC", external_id="1")
    b = _source(source_id="arxiv:1", provider=SourceProvider.ARXIV, doi="10.1/abc", external_id="1")

    merged = merge_results([a, b], max_total=10)

    assert len(merged) == 1
    assert "merged_providers" in merged[0].metadata
    assert set(merged[0].metadata["merged_providers"]) == {"semantic_scholar", "arxiv"}


def test_merge_does_not_merge_different_papers_with_similar_titles():
    a = _source(source_id="a", external_id="1111.1111", title="Battery chemistry overview", publication_year=2020)
    b = _source(source_id="b", external_id="2222.2222", title="Battery chemistry trends", publication_year=2021)

    merged = merge_results([a, b], max_total=10)

    assert len(merged) == 2


def test_merge_respects_max_total():
    sources = [
        _source(source_id=f"s{i}", external_id=f"{i}.{i}", title=f"Unique title number {i}")
        for i in range(5)
    ]
    merged = merge_results(sources, max_total=3)
    assert len(merged) == 3


def test_rank_prefers_peer_reviewed_and_open_access():
    weak = _source(
        source_id="weak",
        publication_status=PublicationStatus.UNKNOWN,
        is_open_access=False,
    )
    strong = _source(
        source_id="strong",
        publication_status=PublicationStatus.PEER_REVIEWED,
        is_open_access=True,
        abstract="has an abstract",
    )
    ranked = rank_sources([weak, strong])
    assert ranked[0].source_id == "strong"


def test_merge_handles_multi_query_duplicate_collision():
    # Source A with strong DOI and title
    a = _source(source_id="s1", doi="10.1000/1", title="Tesla vs BYD Battery Strategy", publication_year=2024)
    # Source B matches A by strong DOI
    b = _source(source_id="s2", doi="10.1000/1", title="Tesla vs BYD Battery Strategy Overview", publication_year=2024)
    # Source C matches A by title and year
    c = _source(source_id="s3", doi=None, title="Tesla vs BYD Battery Strategy", publication_year=2024)

    # Must merge all 3 without throwing ValueError: Source is not in list
    merged = merge_results([a, b, c], max_total=10)
    assert len(merged) == 1
