#!/usr/bin/env python3
"""
packetsplitter - Split PDF files at top-level bookmarks into separate files.
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


def sanitize_filename(title: str, max_length: int = 200) -> str:
    """
    Sanitize a bookmark title for use as a filename.

    - Replaces unsafe characters with underscores
    - Normalizes unicode
    - Collapses whitespace
    - Truncates at word boundary
    """
    # Normalize unicode to composed form
    title = unicodedata.normalize("NFC", title)

    # Replace unsafe filesystem characters
    unsafe_chars = r'/\:*?"<>|'
    for char in unsafe_chars:
        title = title.replace(char, "_")

    # Collapse multiple whitespace/underscores into single space
    title = re.sub(r"[\s_]+", " ", title)
    title = title.strip()

    # Truncate at word boundary if too long
    if len(title) > max_length:
        truncated = title[:max_length]
        # Find last space to avoid cutting words
        last_space = truncated.rfind(" ")
        if last_space > max_length // 2:
            title = truncated[:last_space]
        else:
            title = truncated

    return title.strip() or "untitled"


def get_unique_filename(output_dir: Path, base_name: str, used_names: set) -> Path:
    """
    Generate a unique filename, adding counter for duplicates.

    Returns paths like: title.pdf, title (1).pdf, title (2).pdf
    """
    candidate = base_name
    counter = 0

    while candidate.lower() in used_names:
        counter += 1
        candidate = f"{base_name} ({counter})"

    used_names.add(candidate.lower())
    return output_dir / f"{candidate}.pdf"


def extract_top_level_bookmarks(reader: PdfReader) -> list[tuple[str, int]]:
    """
    Extract top-level bookmarks with their page numbers.

    Returns list of (title, page_number) tuples, sorted by page number.
    Skips nested bookmark lists.
    """
    bookmarks = []

    if not reader.outline:
        return bookmarks

    for item in reader.outline:
        # Skip nested bookmark lists
        if isinstance(item, list):
            continue

        try:
            title = item.title
            page_num = reader.get_destination_page_number(item)
            bookmarks.append((title, page_num))
        except (AttributeError, KeyError, TypeError):
            # Skip malformed bookmarks
            continue

    # Sort by page number to ensure correct ordering
    bookmarks.sort(key=lambda x: x[1])
    return bookmarks


def calculate_page_ranges(
    bookmarks: list[tuple[str, int]], total_pages: int
) -> list[tuple[str, int, int]]:
    """
    Calculate page ranges for each bookmark section.

    Returns list of (title, start_page, end_page) tuples.
    end_page is inclusive.
    """
    ranges = []

    for i, (title, start_page) in enumerate(bookmarks):
        if i + 1 < len(bookmarks):
            # End at page before next bookmark
            end_page = bookmarks[i + 1][1] - 1
        else:
            # Last bookmark goes to end of document
            end_page = total_pages - 1

        # Ensure valid range
        if end_page >= start_page:
            ranges.append((title, start_page, end_page))

    return ranges


def split_pdf(
    input_path: Path,
    output_dir: Path,
    verbose: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Split a PDF at top-level bookmarks into separate files.

    Returns the number of files created (or would be created in dry-run mode).
    """
    # Read the input PDF
    try:
        reader = PdfReader(input_path)
    except PdfReadError as e:
        print(f"Error: Cannot read PDF file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to open PDF: {e}", file=sys.stderr)
        sys.exit(1)

    total_pages = len(reader.pages)
    if verbose:
        print(f"Opened {input_path.name} ({total_pages} pages)")

    # Extract bookmarks
    bookmarks = extract_top_level_bookmarks(reader)

    if not bookmarks:
        print("Error: No top-level bookmarks found in PDF", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"Found {len(bookmarks)} top-level bookmark(s)")

    # Calculate page ranges
    ranges = calculate_page_ranges(bookmarks, total_pages)

    # Create output directory if needed (unless dry-run)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Track used filenames to handle duplicates
    used_names: set[str] = set()
    files_created = 0

    for title, start_page, end_page in ranges:
        # Generate safe filename
        safe_name = sanitize_filename(title)
        output_path = get_unique_filename(output_dir, safe_name, used_names)

        page_count = end_page - start_page + 1

        if dry_run:
            print(f"Would create: {output_path.name}")
            print(f"  Pages {start_page + 1}-{end_page + 1} ({page_count} page(s))")
            print(f"  Bookmark: {title}")
        else:
            if verbose:
                print(f"Creating: {output_path.name}")
                print(f"  Pages {start_page + 1}-{end_page + 1} ({page_count} page(s))")

            # Create new PDF with the page range
            writer = PdfWriter()
            for page_num in range(start_page, end_page + 1):
                writer.add_page(reader.pages[page_num])

            try:
                with open(output_path, "wb") as f:
                    writer.write(f)
            except PermissionError:
                print(
                    f"Error: Permission denied writing to {output_path}",
                    file=sys.stderr,
                )
                sys.exit(1)
            except OSError as e:
                print(f"Error: Failed to write {output_path}: {e}", file=sys.stderr)
                sys.exit(1)

        files_created += 1

    return files_created


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="packetsplitter",
        description="Split a PDF file at top-level bookmarks into separate files.",
    )
    parser.add_argument(
        "input_pdf",
        type=Path,
        help="PDF file to split",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview splits without creating files",
    )

    args = parser.parse_args()

    # Validate input file
    if not args.input_pdf.exists():
        print(f"Error: File not found: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    if not args.input_pdf.is_file():
        print(f"Error: Not a file: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    # Run the split
    count = split_pdf(
        input_path=args.input_pdf,
        output_dir=args.output_dir,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    # Summary
    action = "Would create" if args.dry_run else "Created"
    print(f"\n{action} {count} file(s)")


if __name__ == "__main__":
    main()
