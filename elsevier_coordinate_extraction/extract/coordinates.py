"""Coordinate extraction logic."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Tuple

import os
import pandas as pd
from lxml import etree
from pubget._coordinate_space import _neurosynth_guess_space
from pubget._coordinates import _extract_coordinates_from_table

from elsevier_coordinate_extraction.table_extraction import extract_tables_from_article
from elsevier_coordinate_extraction.types import ArticleContent, TableMetadata
from elsevier_coordinate_extraction import settings


def extract_coordinates(articles: Iterable[ArticleContent]) -> dict:
    """Extract coordinate tables from the supplied articles."""

    article_list = list(articles)
    if not article_list:
        return {"studyset": {"studies": []}}

    cfg = settings.get_settings()
    user_workers = cfg.extraction_workers
    if user_workers <= 0:
        worker_count = min(len(article_list), max(os.cpu_count() or 1, 1))
    else:
        worker_count = min(len(article_list), user_workers)
    if worker_count == 1:
        studies = [_build_study(article) for article in article_list]
    else:
        indexed_results: list[tuple[int, dict[str, Any]]] = []
        with ProcessPoolExecutor(max_workers=worker_count) as pool:
            future_map = {
                pool.submit(_build_study, article): idx
                for idx, article in enumerate(article_list)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                indexed_results.append((idx, future.result()))
        indexed_results.sort(key=lambda pair: pair[0])
        studies = [study for _, study in indexed_results]

    return {"studyset": {"studies": studies}}


def _build_study(article: ArticleContent) -> dict[str, Any]:
    """Process a single article into a study representation."""

    analyses: list[dict[str, Any]] = []
    article_text: str | None = None
    tables = extract_tables_from_article(article.payload)
    if not tables:
        tables = _manual_extract_tables(article.payload)
    for metadata, df in tables:
        meta_text = _metadata_text(metadata)
        coords = _extract_coordinates_from_dataframe(df)
        if not coords:
            continue
        header_text = " ".join(str(col).lower() for col in df.columns)
        space = _heuristic_space(header_text, meta_text)
        if space is None:
            article_text = _article_text(article.payload)
            guessed = _neurosynth_guess_space(article_text)
            if guessed != "UNKNOWN":
                space = guessed
        analysis_metadata = {
            "table_label": metadata.label,
            "table_id": metadata.identifier,
            "raw_table_xml": metadata.raw_xml,
        }
        if metadata.reference_sentences:
            analysis_metadata["reference_sentences"] = metadata.reference_sentences
        points = [
            {
                "coordinates": triplet,
                "space": space,
            }
            for triplet in coords
        ]
        if not points:
            continue
        analysis_name = _analysis_name(metadata)
        analyses.append(
            {"name": analysis_name, "points": points, "metadata": analysis_metadata}
        )
    study_metadata = dict(article.metadata)
    return {
        "doi": article.doi,
        "analyses": analyses,
        "metadata": study_metadata,
    }


def _heuristic_space(header_text: str, meta_text: str) -> str | None:
    combined = f"{header_text} {meta_text}".strip()
    if not combined:
        return None
    combined = combined.lower()
    if "mni" in combined or "montreal" in combined:
        return "MNI"
    tal_tokens = ("talair", "talairach", "talairac", "talairarch", "tala")
    if any(token in combined for token in tal_tokens):
        return "TAL"
    if "spm" in combined and "coordinate" in combined:
        return "MNI"
    return None


def _metadata_text(metadata: TableMetadata) -> str:
    parts: list[str] = []
    for value in (
        metadata.caption,
        metadata.label,
        metadata.legend,
        metadata.foot,
    ):
        if value:
            parts.append(value)
    if metadata.reference_sentences:
        parts.extend(metadata.reference_sentences)
    raw_xml = metadata.raw_xml
    if raw_xml:
        try:
            element = etree.fromstring(raw_xml.encode("utf-8"))
        except (etree.XMLSyntaxError, ValueError):
            parts.append(raw_xml)
        else:
            extra = [
                text.strip()
                for text in element.xpath(
                    '//text()[not(ancestor::*[local-name()="tgroup"])]'
                )
                if text and text.strip()
            ]
            parts.extend(extra)
    return " ".join(parts)


def _analysis_name(metadata: TableMetadata) -> str:
    for candidate in (metadata.caption, metadata.label, metadata.legend):
        if candidate:
            return candidate
    raw_xml = metadata.raw_xml
    if raw_xml:
        try:
            element = etree.fromstring(raw_xml.encode("utf-8"))
        except (etree.XMLSyntaxError, ValueError):
            pass
        else:
            texts = [
                text.strip()
                for text in element.xpath(
                    './/*[local-name()="caption" or local-name()="label"]//text()'
                )
                if text and text.strip()
            ]
            if texts:
                return texts[0]
    return "Coordinate Table"


def _article_text(payload: bytes) -> str:
    root = etree.fromstring(payload)
    return " ".join(root.xpath(".//text()"))


def _reference_sentences(
    root: etree._Element, table_id: str | None
) -> list[str]:
    if not table_id:
        return []
    xpath = (
        './/*[local-name()="cross-ref" or local-name()="cross-refs"]'
        '[contains(concat(" ", normalize-space(@refid), " "), '
        'concat(" ", $table_id, " "))]'
    )
    ref_nodes = root.xpath(xpath, table_id=table_id)
    sentences: list[str] = []
    seen: set[int] = set()
    for node in ref_nodes:
        parents = node.xpath(
            'ancestor::*[local-name()="para" or local-name()="simple-para"][1]'
        )
        if not parents:
            continue
        para = parents[0]
        marker = id(para)
        if marker in seen:
            continue
        seen.add(marker)
        text = " ".join(" ".join(para.itertext()).split())
        if text:
            sentences.append(text)
    return sentences


def _manual_extract_tables(payload: bytes) -> list[Tuple[TableMetadata, pd.DataFrame]]:
    parser = etree.XMLParser(remove_blank_text=True)
    try:
        root = etree.fromstring(payload, parser=parser)
    except etree.XMLSyntaxError:
        return []
    tables: list[Tuple[TableMetadata, pd.DataFrame]] = []
    for table in root.xpath('.//*[local-name()="table"]'):
        parent = table.getparent()
        context = parent if parent is not None else table
        label = _first_text(context, './/*[local-name()="label"]')
        caption = _first_text(context, './/*[local-name()="caption"]')
        legend = _first_text(context, './/*[local-name()="legend"]')
        foot = _first_text(
            context,
            './/*[local-name()="table-foot" or local-name()="table-wrap-foot"]',
        )
        identifier = table.get("id")
        references = _reference_sentences(root, identifier)
        df = _table_to_dataframe(table)
        if df is None or df.empty:
            continue
        raw_element = parent if parent is not None else table
        raw_xml = etree.tostring(raw_element, encoding="unicode")
        metadata = TableMetadata(
            label=label,
            identifier=identifier,
            caption=caption,
            legend=legend,
            foot=foot,
            raw_xml=raw_xml,
            reference_sentences=references,
        )
        tables.append((metadata, df))
    return tables


def _first_text(node: etree._Element, xpath: str) -> str | None:
    result = node.xpath(xpath)
    if not result:
        return None
    text = " ".join(result[0].itertext()).strip()
    return text or None


def _table_to_dataframe(table: etree._Element) -> pd.DataFrame | None:
    ns_cals = {"cals": "http://www.elsevier.com/xml/common/cals/dtd"}
    tgroups = table.xpath("./cals:tgroup", namespaces=ns_cals)
    if tgroups:
        df = _cals_table_to_dataframe(tgroups[0])
        if df is not None:
            return df

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
    max_len = max(len(r) for r in rows)
    normalized = [r + [""] * (max_len - len(r)) for r in rows]
    header = normalized[0]
    data = normalized[1:]
    return pd.DataFrame(data, columns=[str(h) for h in header])


def _cals_table_to_dataframe(tgroup: etree._Element) -> pd.DataFrame | None:
    ns = {"cals": "http://www.elsevier.com/xml/common/cals/dtd"}
    colspecs = tgroup.xpath("./cals:colspec", namespaces=ns)
    if not colspecs:
        return None
    col_order = [
        spec.get("colname") or f"col{idx+1}" for idx, spec in enumerate(colspecs)
    ]
    col_index = {name: idx for idx, name in enumerate(col_order)}
    n_cols = len(col_order)

    def _rows(xpath: str) -> list[etree._Element]:
        return tgroup.xpath(xpath, namespaces=ns)

    row_elements = _rows("./cals:thead/cals:row") + _rows("./cals:tbody/cals:row")
    if not row_elements:
        row_elements = _rows(".//cals:row")
    if not row_elements:
        return None

    pending: list[dict[str, Any] | None] = [None] * n_cols
    grid: list[list[str]] = []

    for row in row_elements:
        values = ["" for _ in range(n_cols)]
        filled = [False] * n_cols
        # Prefill values from rowspans
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
                while pointer < n_cols and filled[pointer]:
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

            if start >= n_cols:
                continue
            for offset in range(span):
                idx = start + offset
                if idx >= n_cols:
                    break
                values[idx] = text if offset == 0 else ""
                filled[idx] = True
            pointer = max(pointer, start + span)

            if rowspan > 1:
                for offset in range(span):
                    idx = start + offset
                    if idx >= n_cols:
                        continue
                    pending[idx] = {"text": text, "remaining": rowspan - 1}

        grid.append(values)

    if len(grid) <= 1:
        return None
    return pd.DataFrame(grid, columns=col_order)


def _extract_coordinates_from_dataframe(df: pd.DataFrame) -> list[list[float]]:
    df = _normalize_table(df)
    extracted = _extract_coordinates_from_table(df)
    if not extracted.empty:
        extracted = extracted.apply(pd.to_numeric, errors="coerce").dropna()
        return [
            [float(row.x), float(row.y), float(row.z)]
            for row in extracted.itertuples(index=False)
        ]
    return []


def _normalize_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()

    # Identify a header row that contains x/y/z, even if preceded by title rows.
    max_header_rows = min(5, len(df))
    header_rows: list[list[str]] = [
        [str(value).strip() for value in df.iloc[idx]] for idx in range(max_header_rows)
    ]
    header_row_index: int | None = None
    for idx, row in enumerate(header_rows):
        lowered = {value.lower() for value in row if value}
        if {"x", "y", "z"}.issubset(lowered):
            header_row_index = idx
            break

    if header_row_index is not None:
        combined_headers: list[str] = []
        for col_idx in range(df.shape[1]):
            header_value: str | None = None
            for idx in range(header_row_index, -1, -1):
                cell = header_rows[idx][col_idx]
                if cell:
                    header_value = cell
                    break
            if not header_value:
                header_value = str(df.columns[col_idx])
            combined_headers.append(header_value)
        df.columns = combined_headers
        df = df.iloc[header_row_index + 1 :].reset_index(drop=True)
    else:
        first_row = [str(value).strip().lower() for value in df.iloc[0]]
        if {"x", "y", "z"}.issubset(first_row):
            rename_map = {}
            for idx, value in enumerate(first_row):
                if value in {"x", "y", "z"}:
                    rename_map[df.columns[idx]] = value
            df = df.iloc[1:].reset_index(drop=True)
            df = df.rename(columns=rename_map)

    df = df.loc[:, ~df.columns.duplicated()]
    df = df.dropna(axis=1, how="all")
    xyz_cols = [col for col in ("x", "y", "z") if col in df.columns]
    if len(xyz_cols) == 3:
        other_cols = [col for col in df.columns if col not in xyz_cols]
        df = df[list(xyz_cols) + other_cols]
    return df
