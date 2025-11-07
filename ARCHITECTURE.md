# Architecture Overview

This document contains a plain language overview of the architecture of the Elsvier Coordinate Extraction package.

## Core Components
The package is structured into three main components:
1. **Search Module**: Responsible for querying Elsevier's database to find relevant articles based on user-defined criteria.
2. **Download Module**: Handles the downloading of articles identified by the Search Module.
3. **Extraction Module**: Focuses on extracting coordinate data from the downloaded articles.

These components are modular and independent, allowing
for piecewise development and testing, and integration
into other code bases.


## Data Flow
The data flow within the package follows a linear progression:
1. **Input**: User provides search criteria (e.g., keywords, authors).
2. **Search**: The Search Module queries the Elsevier database and returns a list of articles matching the criteria.
3. **Download**: The Download Module retrieves the full text of the articles identified in the search results.
4. **Extraction**: The Extraction Module processes the downloaded articles to extract relevant coordinate data.
5. **Output**: The extracted coordinates are returned to the user in a structured format (following the nimads standard: https://neurostuff.github.io/NIMADS/).

### Input

This will be a search query string, trying to faithfully
represent the searches that can be done with the elsevier API.

### Search

Using the elsevier API, we will search for articles
matching the input query. The results will be a list of
articles with metadata including their unique identifiers.
The output of this stage is a list of article identifiers in a dictionary format.
I'm looking for doi, pmid, pmcid where available.
If only DOI is available, that is sufficient.

### Download

This will take in the list of article identifiers
from the Search stage, and download the full text of
each article. The output of this stage is the full text
of each article in a suitable format for processing
by the Extraction stage. The downloading should be
parallelized while respecting any rate limits imposed by
the Elsevier API.

### Extraction
This stage processes the full text of each downloaded
article to extract coordinate data. The output of this
stage is a structured representation of the extracted
coordinates, following the nimads standard: https://neurostuff.github.io/NIMADS/

This will also be parallelized to improve performance.


## Inspiration

The coordinate extraction is inspired by pubget (https://github.com/neuroquery/pubget)
and ACE (https://github.com/neurosynth/ACE)
