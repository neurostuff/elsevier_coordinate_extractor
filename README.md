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

Additional flags allow users to skip writing specific outputs (`--skip-xml`, `--skip-text`, `--skip-tables`, `--skip-coordinates`), continue past failures (`--continue-on-error`), disable caching (`--no-cache`), or adjust verbosity (`-v/--verbose`, `-q/--quiet`). `--output-dir` controls the base directory for results, and the CLI honors `ELSEVIER_EXTRACTION_WORKERS` when no `--max-workers` override is provided.

### Output layout

Each article is saved under `output-dir/{identifier}` where `{identifier}` is the filesystem-friendly DOI (slashes replaced with `_`) or PMID. Inside that directory you will find:

- `article.xml` – the raw XML payload
- `metadata.json` – download metadata, rate-limit snapshot, and supplementary attachments
- `text.txt` – formatted article text (title/abstract/body)
- `coordinates.json` – NIMADS-style evaluation of extracted coordinates
- `tables/*.csv` – extracted tables named after their labels/captions

The CLI also appends every run to `manifest.jsonl` (with status, timing, and file list) and records failures in `errors.jsonl`, enabling audit and resumable processing.
