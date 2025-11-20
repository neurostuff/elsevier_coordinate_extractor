"""Coordinate extraction tests."""

from __future__ import annotations

import pytest

from elsevier_coordinate_extraction.extract.coordinates import (
    extract_coordinates,
)
from elsevier_coordinate_extraction.types import (
    ArticleContent,
    build_article_content,
)


def _find_points(result: dict) -> list[dict]:
    studies = result.get("studyset", {}).get("studies", [])
    if not studies:
        return []
    analyses = studies[0].get("analyses", [])
    if not analyses:
        return []
    return analyses[0].get("points", [])


@pytest.mark.vcr()
def test_extract_returns_coordinates_for_real_articles(
    downloaded_articles: list[ArticleContent],
) -> None:
    """Aggregated extraction preserves metadata and infers coordinate space."""

    result = extract_coordinates(downloaded_articles)
    studies = result["studyset"]["studies"]
    assert len(studies) == len(downloaded_articles)
    analysis_names: set[str] = set()
    spaces_by_article: dict[str, set[str | None]] = {}
    missing_coordinates: list[str] = []
    is_doi_source = (
        getattr(downloaded_articles, "identifier_type", "doi") == "doi"
    )
    for article, study in zip(downloaded_articles, studies):
        assert study["doi"] == article.doi
        analyses = study["analyses"]
        if not analyses:
            missing_coordinates.append(study["doi"])
            continue
        spaces_by_article[article.doi] = set()
        for analysis in analyses:
            points = analysis["points"]
            assert points, f"Expected coordinate points for {study['doi']}"
            analysis_names.add(analysis["name"])
            analysis_meta = analysis.get("metadata", {})
            assert analysis_meta.get(
                "raw_table_xml"
            ), "raw table XML should be retained"
            table_id = analysis_meta.get("table_id")
            if is_doi_source:
                assert table_id, "table ID should accompany raw table XML"
            for point in points:
                coords = point["coordinates"]
                assert len(coords) == 3
                assert all(isinstance(value, float) for value in coords)
                spaces_by_article[article.doi].add(point.get("space"))
    assert analysis_names, "Expected at least one named analysis"
    if is_doi_source:
        assert (
            "Coordinate Table" not in analysis_names
        ), "Fallback analysis name should be replaced"
    for doi, spaces in spaces_by_article.items():
        assert spaces, f"No coordinate space inferred for {doi}"
        assert any(
            space in {"MNI", "TAL"}
            for space in spaces
            if space
        ), f"No canonical coordinate space detected for {doi}: {spaces}"
    if is_doi_source:
        assert (
            not missing_coordinates
        ), f"Missing coordinate tables for: {missing_coordinates}"
    else:
        assert len(missing_coordinates) < len(downloaded_articles), (
            "No coordinates extracted for any PMID-sourced article."
        )


@pytest.mark.vcr()
def test_extract_preserves_article_metadata(
    downloaded_articles: list[ArticleContent],
) -> None:
    """Ensure DOI and PII are propagated to the study metadata."""
    result = extract_coordinates(downloaded_articles)
    studies = result["studyset"]["studies"]
    for study, article in zip(studies, downloaded_articles):
        assert study["doi"] == article.doi
        if "pii" in article.metadata:
            assert study["metadata"]["pii"] == article.metadata.get("pii")


def test_extract_coordinates_from_synthetic_table() -> None:
    """Synthetic article with coordinate table should yield points."""
    payload = b"""
    <article>
      <body>
        <table-wrap id="tbl1">
          <label>Table 1</label>
          <table>
            <thead>
              <tr><th>X (MNI)</th><th>Y (MNI)</th><th>Z (MNI)</th></tr>
            </thead>
            <tbody>
              <tr><td>10</td><td>20</td><td>30</td></tr>
              <tr><td>-12</td><td>18</td><td>40</td></tr>
            </tbody>
          </table>
        </table-wrap>
      </body>
    </article>
    """
    article = build_article_content(
        doi="synthetic-doi",
        payload=payload,
        content_type="text/xml",
        format="xml",
        metadata={},
    )
    result = extract_coordinates([article])
    points = _find_points(result)
    assert len(points) == 2
    assert points[0]["coordinates"] == [10.0, 20.0, 30.0]
    assert points[0]["space"] == "MNI"
