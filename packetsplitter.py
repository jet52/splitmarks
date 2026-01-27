#!/usr/bin/env python3
"""
packetsplitter - Split PDF files at top-level bookmarks into separate files.
"""

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


@dataclass
class Bookmark:
    """Represents a bookmark with its children."""

    title: str
    page_num: int
    children: list["Bookmark"] = field(default_factory=list)


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


def parse_outline_tree(reader: PdfReader, outline: list | None = None) -> list[Bookmark]:
    """
    Recursively parse the PDF outline into a tree of Bookmark objects.

    Returns list of top-level Bookmark objects, each with nested children.
    """
    if outline is None:
        outline = reader.outline

    if not outline:
        return []

    bookmarks = []
    i = 0

    while i < len(outline):
        item = outline[i]

        if isinstance(item, list):
            # This is a nested list of children for the previous bookmark
            if bookmarks:
                bookmarks[-1].children = parse_outline_tree(reader, item)
            i += 1
            continue

        try:
            title = item.title
            page_num = reader.get_destination_page_number(item)
            bookmarks.append(Bookmark(title=title, page_num=page_num))
        except (AttributeError, KeyError, TypeError):
            # Skip malformed bookmarks
            pass

        i += 1

    return bookmarks


def get_top_level_bookmarks(bookmarks: list[Bookmark]) -> list[tuple[str, int]]:
    """
    Extract just the top-level bookmark info for splitting.

    Returns list of (title, page_number) tuples, sorted by page number.
    """
    result = [(b.title, b.page_num) for b in bookmarks]
    result.sort(key=lambda x: x[1])
    return result


def add_bookmarks_to_writer(
    writer: PdfWriter,
    bookmark: Bookmark,
    start_page: int,
    end_page: int,
    parent=None,
) -> None:
    """
    Recursively add a bookmark and its children to the writer.

    Only includes bookmarks whose pages fall within the given range.
    Page numbers are adjusted relative to start_page.
    """
    # Check if this bookmark's page is within range
    if start_page <= bookmark.page_num <= end_page:
        # Adjust page number to be relative to the split file
        adjusted_page = bookmark.page_num - start_page

        # Add the bookmark
        outline_item = writer.add_outline_item(
            title=bookmark.title,
            page_number=adjusted_page,
            parent=parent,
        )

        # Recursively add children
        for child in bookmark.children:
            add_bookmarks_to_writer(writer, child, start_page, end_page, outline_item)


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

    # Parse full bookmark tree
    bookmark_tree = parse_outline_tree(reader)

    if not bookmark_tree:
        print("Error: No top-level bookmarks found in PDF", file=sys.stderr)
        sys.exit(1)

    # Get top-level bookmarks for splitting
    top_level = get_top_level_bookmarks(bookmark_tree)

    if verbose:
        print(f"Found {len(top_level)} top-level bookmark(s)")

    # Calculate page ranges
    ranges = calculate_page_ranges(top_level, total_pages)

    # Create output directory if needed (unless dry-run)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Track used filenames to handle duplicates
    used_names: set[str] = set()
    files_created = 0

    # Create a mapping from top-level title to its Bookmark object
    bookmark_by_title = {b.title: b for b in bookmark_tree}

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

            # Add bookmarks for this section
            if title in bookmark_by_title:
                top_bookmark = bookmark_by_title[title]
                add_bookmarks_to_writer(writer, top_bookmark, start_page, end_page)

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
