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
