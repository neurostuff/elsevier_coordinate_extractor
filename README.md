# Elsvier Coordinate Extraction

This package provides tools to search, download, and
extract coordinates from Elseivier articles.

## Installation

pip install elsvier-coordinate-extraction

or a local install:
```bash
git clone https://github.com/yourusername/elsevier-coordinate-extraction.git
cd elsevier-coordinate-extraction
pip install -e .
```

## Usage

```python
from elsvier_coordinate_extraction import search_articles, download_articles, extract_coordinates

# Search for articles
articles = search_articles(query="fmri", max_results=5)

# Download full-text XML for the first article using its DOI/PMID
records = [{"doi": articles[0]["doi"], "pmid": articles[0].get("pmid")}]  # type: ignore[index]
downloaded = download_articles(records)

# Extract coordinates
coordinates = extract_coordinates(downloaded)
print(coordinates)
```

## Command-Line Interface

After installing the package, the `elsevier-extract` script becomes available via `pip install .` (or from PyPI). It accepts three mutually exclusive identifier inputs:

- `--pmids` for comma-separated PMIDs or a text file containing one PMID per line
- `--dois` for comma-separated DOIs or a text file containing one DOI per line
- `--jsonl` for a JSON Lines file where each line is `{"doi": "...", "pmid": "..."}`

Download order is fixed to `Elsevier -> Springer Open Access`:

- Elsevier full-text is attempted first for DOI/PMID records.
- On Elsevier miss, PMID-only records are resolved to DOI via NCBI ESummary and retried against Springer Open Access (`/openaccess/json` + `/openaccess/jats`).

Additional flags allow users to skip writing specific outputs (`--skip-xml`, `--skip-text`, `--skip-tables`, `--skip-coordinates`), continue past failures by default (`--continue-on-error`), opt into fail-fast behavior (`--fail-fast`), disable caching (`--no-cache`), or adjust verbosity (`-v/--verbose`, `-q/--quiet`). `--output-dir` controls the base directory for results, and the CLI honors `ELSEVIER_EXTRACTION_WORKERS` when no `--max-workers` override is provided.

### Environment Variables

- Required: `ELSEVIER_API_KEY`
- Optional Springer fallback: `SPRINGER_API_KEY`, `SPRINGER_BASE_URL`
- Optional PubMed resolution: `PUBMED_BASE_URL`, `NCBI_API_KEY`

### Output layout

Each article is saved under `output-dir/{identifier}` where `{identifier}` is the filesystem-friendly DOI (slashes replaced with `_`) or PMID. Inside that directory you will find:

- `article.xml` – the raw XML payload
- `metadata.json` – download metadata, rate-limit snapshot, and supplementary attachments
- `text.txt` – formatted article text (title/abstract/body)
- `coordinates.json` – NIMADS-style evaluation of extracted coordinates
- `tables/*.csv` – extracted tables named after their labels/captions

The CLI also appends every run to `manifest.jsonl` (with status, source provider, timing, file list, and a `reason` field for skipped entries) and records failures in `errors.jsonl` (including provider source), enabling audit and resumable processing. Springer/PubMed skip reasons include:

- `springer_unconfigured`
- `pmid_to_doi_unresolved`
- `springer_not_found`
- `springer_jats_unavailable`
- `springer_rate_limited`
