from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from elsevier_coordinate_extraction.settings import get_settings

from .inputs import (
    parse_dois,
    parse_jsonl,
    parse_pmids,
    validate_records,
)
from .orchestrator import process_articles


DESCRIPTION = """
Download Elsevier articles, extract text/tables/coordinates,
and write structured outputs.
"""

EXAMPLES = """Examples:
  # Download by PubMed IDs inline
  elsevier-extract --pmids 12345678,23456789 --output-dir ./results

  # Download by DOIs from file
  elsevier-extract --dois dois.txt --output-dir ./results

  # Batch from JSONL
  elsevier-extract --jsonl identifiers.jsonl --continue-on-error
"""


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elsevier-extract",
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--pmids", type=str, help="Comma-separated PMIDs or file path"
    )
    input_group.add_argument(
        "--dois", type=str, help="Comma-separated DOIs or file path"
    )
    input_group.add_argument(
        "--jsonl", type=Path, help="JSONL file with doi/pmid records"
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./elsevier_output"),
        help="Base directory for article outputs",
    )
    parser.add_argument(
        "--skip-xml",
        action="store_true",
        help="Skip writing raw XML",
    )
    parser.add_argument(
        "--skip-text",
        action="store_true",
        help="Skip writing extracted text",
    )
    parser.add_argument(
        "--skip-tables",
        action="store_true",
        help="Skip writing extracted tables",
    )
    parser.add_argument(
        "--skip-coordinates",
        action="store_true",
        help="Skip writing coordinates JSON",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep going after failures",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        help="Override extraction worker count",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable response caching",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print progress messages",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal console output",
    )
    return parser


def gather_records(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.pmids:
        return parse_pmids(args.pmids)
    if args.dois:
        return parse_dois(args.dois)
    if args.jsonl:
        return parse_jsonl(args.jsonl)
    return []


async def async_main(args: argparse.Namespace) -> int:
    try:
        records = validate_records(gather_records(args))
    except Exception as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No identifiers were provided.", file=sys.stderr)
        return 1

    settings = get_settings()
    if args.max_workers:
        settings = settings.__class__(
            **{
                **settings.__dict__,
                "extraction_workers": args.max_workers,
            }
        )

    if not args.quiet:
        print(f"Processing {len(records)} article(s)...")

    try:
        stats = await process_articles(
            records,
            args.output_dir,
            settings=settings,
            skip_xml=args.skip_xml,
            skip_text=args.skip_text,
            skip_tables=args.skip_tables,
            skip_coordinates=args.skip_coordinates,
            continue_on_error=args.continue_on_error,
            use_cache=not args.no_cache,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"Processing failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        summary = (
            "\nSummary: success="
            f"{stats['success']} failed={stats['failed']} "
            f"skipped={stats['skipped']}"
        )
        print(summary)

    return 0 if stats["failed"] == 0 else 1


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
