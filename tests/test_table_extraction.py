from __future__ import annotations

from elsevier_coordinate_extraction.table_extraction import extract_tables_from_article


def test_extract_tables_includes_reference_sentences() -> None:
    payload = b"""
    <root xmlns:ce="http://www.elsevier.com/xml/common/dtd">
      <ce:body>
        <ce:section>
          <ce:para>
            This paragraph references
            <ce:cross-ref refid="tbl1">Table 1</ce:cross-ref>
            for coordinates.
          </ce:para>
          <ce:table id="tbl1">
            <ce:label>Table 1</ce:label>
            <ce:caption>Coordinates</ce:caption>
            <ce:tgroup cols="3">
              <ce:thead>
                <ce:row>
                  <ce:entry>X</ce:entry>
                  <ce:entry>Y</ce:entry>
                  <ce:entry>Z</ce:entry>
                </ce:row>
              </ce:thead>
              <ce:tbody>
                <ce:row>
                  <ce:entry>1</ce:entry>
                  <ce:entry>2</ce:entry>
                  <ce:entry>3</ce:entry>
                </ce:row>
              </ce:tbody>
            </ce:tgroup>
          </ce:table>
        </ce:section>
      </ce:body>
    </root>
    """
    tables = extract_tables_from_article(payload)
    assert tables, "Table extraction failed to return any tables"
    metadata, df = tables[0]
    assert df.shape == (1, 3)
    assert metadata.reference_sentences == [
        "This paragraph references Table 1 for coordinates."
    ]
