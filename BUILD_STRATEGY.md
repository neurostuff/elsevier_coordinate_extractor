# Build Strategy
This document outlines the build strategy for our project, detailing the tools, processes, and best practices we follow to ensure efficient and reliable builds.

## Build Tools
- uv
- venv


## Testing

Testing is done using pytest and pytest-recording to
use realistic http interactions without hitting the live APIs every time.

## Continuous Integration

We use GitHub Actions for continuous integration. The CI pipeline includes:
- Linting with ruff
- Running unit tests with pytest


## Writing code

After an initial implementation of the code architecture, we follow a test driven development (TDD) approach to add new features and fix bugs. This ensures that our code is well-tested and reliable.
