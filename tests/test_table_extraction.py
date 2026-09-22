"""Tests for generic table extraction fallbacks."""

from __future__ import annotations

from elsevier_coordinate_extraction.table_extraction import extract_tables_from_article


def test_extract_tables_from_jats_payload() -> None:
    payload = b"""
    <article xmlns="http://jats.nlm.nih.gov">
      <body>
        <table-wrap id="tbl1">
          <label>Table 1</label>
          <caption><title>Coordinate table</title></caption>
          <table>
            <thead>
              <tr><th>x</th><th>y</th><th>z</th></tr>
            </thead>
            <tbody>
              <tr><td>1</td><td>2</td><td>3</td></tr>
            </tbody>
          </table>
        </table-wrap>
      </body>
    </article>
    """
    tables = extract_tables_from_article(payload)
    assert len(tables) == 1
    metadata, dataframe = tables[0]
    assert metadata.identifier == "tbl1"
    assert metadata.caption and "Coordinate table" in metadata.caption
    assert list(dataframe.columns) == ["x", "y", "z"]
    assert dataframe.iloc[0].tolist() == ["1", "2", "3"]
