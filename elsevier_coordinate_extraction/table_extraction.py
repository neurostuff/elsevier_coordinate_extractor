from __future__ import annotations

import io
from functools import lru_cache
from importlib import resources
from typing import Any, List, Tuple

import pandas as pd
from lxml import etree

from elsevier_coordinate_extraction.types import TableMetadata


@lru_cache(maxsize=None)
def _load_stylesheet() -> etree.XSLT:
    """Load the Elsevier table extraction stylesheet."""
    stylesheet_path = resources.files(
        "elsevier_coordinate_extraction.stylesheets"
    ).joinpath("elsevier_table_extraction.xsl")
    with stylesheet_path.open("rb") as fh:
        xslt_doc = etree.parse(fh)
    return etree.XSLT(xslt_doc)


def extract_tables_from_article(payload: bytes) -> List[Tuple[TableMetadata, pd.DataFrame]]:
    """Transform ScienceDirect XML into DataFrames using the XSL stylesheet."""
    try:
        stylesheet = _load_stylesheet()
        document = etree.fromstring(payload)
        transformed = stylesheet(document)  # type: ignore[arg-type]
    except Exception:
        return extract_tables_generic(payload)
    extracted = _parse_extracted_tables(transformed.getroot())
    if extracted:
        return extracted
    return extract_tables_generic(payload)


def extract_tables_generic(payload: bytes) -> List[Tuple[TableMetadata, pd.DataFrame]]:
    """Fallback table extraction that supports JATS and generic XML tables."""
    parser = etree.XMLParser(remove_blank_text=True)
    try:
        root = etree.fromstring(payload, parser=parser)
    except etree.XMLSyntaxError:
        return []

    tables: list[Tuple[TableMetadata, pd.DataFrame]] = []
    seen: set[int] = set()
    candidates = root.xpath(
        './/*[local-name()="table-wrap" or local-name()="table" or local-name()="table-wrap-group"]'
    )
    for candidate in candidates:
        table_node, context_node = _resolve_table_node(candidate)
        if table_node is None:
            continue
        marker = id(table_node)
        if marker in seen:
            continue
        seen.add(marker)

        dataframe = _table_to_dataframe(table_node)
        if dataframe is None or dataframe.empty:
            continue

        metadata = TableMetadata(
            label=_first_text(context_node, './/*[local-name()="label"]'),
            identifier=table_node.get("id") or context_node.get("id"),
            caption=_first_text(context_node, './/*[local-name()="caption"]'),
            legend=_first_text(context_node, './/*[local-name()="legend"]'),
            foot=_first_text(
                context_node,
                './/*[local-name()="table-foot" or local-name()="table-wrap-foot"]',
            ),
            raw_xml=etree.tostring(context_node, encoding="unicode"),
        )
        tables.append((metadata, dataframe))
    return tables


def _parse_extracted_tables(root: etree._Element) -> List[Tuple[TableMetadata, pd.DataFrame]]:
    tables: List[Tuple[TableMetadata, pd.DataFrame]] = []
    for extracted_table in root.findall("extracted-table"):
        metadata = _build_metadata(extracted_table)
        html_table = extracted_table.find("transformed-table/table")
        if html_table is None:
            continue
        table_str = etree.tostring(html_table, encoding="unicode")
        kwargs = {}
        if not html_table.xpath(".//th"):
            kwargs["header"] = 0
        try:
            df = pd.read_html(
                io.StringIO(table_str), flavor="lxml", thousands=None, **kwargs
            )[0]
        except (ValueError, IndexError):
            continue
        tables.append((metadata, df))
    return tables


def _build_metadata(node: etree._Element) -> TableMetadata:
    def _text(tag: str) -> str | None:
        element = node.find(tag)
        if element is None:
            return None
        text = " ".join(element.itertext()).strip()
        return text or None

    original = node.find("original-table/*")
    raw_xml = None
    if original is not None:
        raw_xml = etree.tostring(original, encoding="unicode")
    return TableMetadata(
        label=_text("table-label"),
        identifier=_text("table-id"),
        caption=_text("table-caption"),
        legend=_text("table-legend"),
        foot=_text("table-wrap-foot"),
        raw_xml=raw_xml,
    )


def _resolve_table_node(
    candidate: etree._Element,
) -> tuple[etree._Element | None, etree._Element]:
    local_name = etree.QName(candidate).localname
    if local_name == "table":
        return candidate, candidate
    table_nodes = candidate.xpath('.//*[local-name()="table"]')
    if not table_nodes:
        return None, candidate
    return table_nodes[0], candidate


def _first_text(node: etree._Element, xpath: str) -> str | None:
    matches = node.xpath(xpath)
    if not matches:
        return None
    first = matches[0]
    if not isinstance(first, etree._Element):
        text = str(first).strip()
        return text or None
    text = " ".join(first.itertext()).strip()
    return text or None


def _table_to_dataframe(table: etree._Element) -> pd.DataFrame | None:
    ns_cals = {"cals": "http://www.elsevier.com/xml/common/cals/dtd"}
    tgroups = table.xpath("./cals:tgroup", namespaces=ns_cals)
    if tgroups:
        dataframe = _cals_table_to_dataframe(tgroups[0])
        if dataframe is not None:
            return dataframe

    row_elements = table.xpath('.//*[local-name()="tr"]')
    cell_xpath = './*[local-name()="th" or local-name()="td"]'
    if not row_elements:
        row_elements = table.xpath('.//*[local-name()="row"]')
        cell_xpath = './*[local-name()="entry"]'
    rows: list[list[str]] = []
    for row in row_elements:
        cells = [" ".join(cell.itertext()).strip() for cell in row.xpath(cell_xpath)]
        if cells:
            rows.append(cells)
    if len(rows) <= 1:
        return None
    max_len = max(len(row) for row in rows)
    normalized = [row + [""] * (max_len - len(row)) for row in rows]
    header = normalized[0]
    data = normalized[1:]
    return pd.DataFrame(data, columns=[str(value) for value in header])


def _cals_table_to_dataframe(tgroup: etree._Element) -> pd.DataFrame | None:
    ns = {"cals": "http://www.elsevier.com/xml/common/cals/dtd"}
    colspecs = tgroup.xpath("./cals:colspec", namespaces=ns)
    if not colspecs:
        return None
    col_order = [
        spec.get("colname") or f"col{idx + 1}"
        for idx, spec in enumerate(colspecs)
    ]
    col_index = {name: idx for idx, name in enumerate(col_order)}
    column_count = len(col_order)

    def _rows(xpath: str) -> list[etree._Element]:
        return tgroup.xpath(xpath, namespaces=ns)

    row_elements = _rows("./cals:thead/cals:row") + _rows("./cals:tbody/cals:row")
    if not row_elements:
        row_elements = _rows(".//cals:row")
    if not row_elements:
        return None

    pending: list[dict[str, Any] | None] = [None] * column_count
    grid: list[list[str]] = []

    for row in row_elements:
        values = ["" for _ in range(column_count)]
        filled = [False] * column_count
        for idx, span in enumerate(pending):
            if span is None:
                continue
            values[idx] = span["text"]
            filled[idx] = True
            span["remaining"] -= 1
            if span["remaining"] <= 0:
                pending[idx] = None

        pointer = 0
        for cell in row:
            if cell.tag.split("}")[-1] != "entry":
                continue
            text = " ".join(cell.itertext()).strip()
            rowspan_raw = cell.get("morerows")
            try:
                rowspan = int(rowspan_raw) + 1 if rowspan_raw is not None else 1
            except ValueError:
                rowspan = 1

            if "colname" in cell.attrib:
                start = col_index.get(cell.attrib["colname"], pointer)
            elif "namest" in cell.attrib:
                start = col_index.get(cell.attrib["namest"], pointer)
            else:
                while pointer < column_count and filled[pointer]:
                    pointer += 1
                start = pointer

            span = 1
            if "nameend" in cell.attrib:
                end = col_index.get(cell.attrib["nameend"], start)
                span = max(1, end - start + 1)
            elif "colspan" in cell.attrib:
                colspan_raw = cell.attrib["colspan"]
                try:
                    span = max(1, int(colspan_raw))
                except ValueError:
                    span = 1

            if start >= column_count:
                continue
            for offset in range(span):
                idx = start + offset
                if idx >= column_count:
                    break
                values[idx] = text if offset == 0 else ""
                filled[idx] = True
            pointer = max(pointer, start + span)

            if rowspan > 1:
                for offset in range(span):
                    idx = start + offset
                    if idx >= column_count:
                        continue
                    pending[idx] = {"text": text, "remaining": rowspan - 1}

        grid.append(values)

    if len(grid) <= 1:
        return None
    return pd.DataFrame(grid, columns=col_order)
