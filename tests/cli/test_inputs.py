from pathlib import Path

import json
import pytest

from elsevier_coordinate_extraction.cli.inputs import (
    parse_dois,
    parse_jsonl,
    parse_pmids,
)


def test_parse_pmids_inline():
    records = parse_pmids("12345678,23456789")
    assert records == [{"pmid": "12345678"}, {"pmid": "23456789"}]


def test_parse_pmids_from_file(tmp_path: Path):
    pmid_file = tmp_path / "pmids.txt"
    pmid_file.write_text("12345678\n# comment\n\n23456789\n")
    records = parse_pmids(str(pmid_file))
    assert records == [{"pmid": "12345678"}, {"pmid": "23456789"}]


def test_parse_dois_inline():
    records = parse_dois("10.1016/one,10.1016/two")
    assert records == [{"doi": "10.1016/one"}, {"doi": "10.1016/two"}]


def test_parse_dois_from_file(tmp_path: Path):
    doi_file = tmp_path / "dois.txt"
    doi_file.write_text("10.1016/one\n10.1016/two\n")
    records = parse_dois(str(doi_file))
    assert records == [{"doi": "10.1016/one"}, {"doi": "10.1016/two"}]


def test_parse_jsonl(tmp_path: Path):
    jsonl_file = tmp_path / "ids.jsonl"
    payloads = [
        {"doi": "10.1016/one", "pmid": "123"},
        {"pmid": "234"},
    ]
    jsonl_file.write_text(
        "\n".join(json.dumps(payload) for payload in payloads)
    )
    records = parse_jsonl(jsonl_file)
    assert records == [{"doi": "10.1016/one", "pmid": "123"}, {"pmid": "234"}]


def test_parse_jsonl_invalid(tmp_path: Path):
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text("not-json")
    with pytest.raises(ValueError):
        parse_jsonl(bad_file)
