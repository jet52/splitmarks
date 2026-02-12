#!/usr/bin/env python3
"""
splitmarks - Split PDF files at top-level bookmarks into separate files.
"""

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

__version__ = "1.4.0"


@dataclass
class Bookmark:
    """Represents a bookmark with its children."""

    title: str
    page_num: int
    children: list["Bookmark"] = field(default_factory=list)


def extract_case_number(text: str) -> str | None:
    """Extract an 8-digit case number from text."""
    match = re.search(r"(?<!\d)(\d{8})(?!\d)", text)
    return match.group(1) if match else None


def contains_case_number(text: str) -> bool:
    """Check if text contains an 8-digit number."""
    return bool(re.search(r"(?<!\d)\d{8}(?!\d)", text))


def sanitize_filename(title: str, max_length: int = 200) -> str:
    """
    Sanitize a bookmark title for use as a filename.

    - Replaces unsafe characters with hyphens
    - Normalizes unicode
    - Collapses whitespace to hyphens
    - Truncates at word boundary
    """
    # Normalize unicode to composed form
    title = unicodedata.normalize("NFC", title)

    # Replace unsafe filesystem characters with hyphens
    unsafe_chars = r'/\:*?"<>|'
    for char in unsafe_chars:
        title = title.replace(char, "-")

    # Collapse multiple whitespace/underscores/hyphens into single hyphen
    title = re.sub(r"[\s_-]+", "-", title)
    title = title.strip("-")

    # Truncate at word boundary if too long
    if len(title) > max_length:
        truncated = title[:max_length]
        # Find last hyphen to avoid cutting words
        last_hyphen = truncated.rfind("-")
        if last_hyphen > max_length // 2:
            title = truncated[:last_hyphen]
        else:
            title = truncated

    return title.strip("-") or "untitled"


def get_unique_filename(output_dir: Path, base_name: str, used_names: set) -> Path:
    """
    Generate a unique filename, adding counter for duplicates.

    Returns paths like: title.pdf, title-1.pdf, title-2.pdf
    """
    candidate = base_name
    counter = 0

    while candidate.lower() in used_names:
        counter += 1
        candidate = f"{base_name}-{counter}"

    used_names.add(candidate.lower())
    return output_dir / f"{candidate}.pdf"


def _resolve_page_number(pdf: pikepdf.Pdf, outline_node) -> int | None:
    """
    Resolve a bookmark's page number from either /Dest or /A (GoTo action).

    Returns 0-based page index, or None if unresolvable.
    """
    # Try direct destination first
    dest = None
    if hasattr(outline_node, "destination") and outline_node.destination:
        dest = outline_node.destination
    elif hasattr(outline_node, "obj") and outline_node.obj:
        obj = outline_node.obj
        if "/Dest" in obj and obj["/Dest"] is not None:
            dest = obj["/Dest"]
        elif "/A" in obj:
            action = obj["/A"]
            if action.get("/S") == pikepdf.Name("/GoTo") and "/D" in action:
                dest = action["/D"]

    if dest is None:
        return None

    try:
        page_ref = dest[0]
        return pdf.pages.index(page_ref)
    except (IndexError, ValueError, TypeError):
        return None


def _parse_outline_items(pdf: pikepdf.Pdf, items) -> list[Bookmark]:
    """Recursively parse outline items into Bookmark objects."""
    bookmarks = []
    for item in items:
        page_num = _resolve_page_number(pdf, item)
        if page_num is None:
            continue
        children = []
        if item.children:
            children = _parse_outline_items(pdf, item.children)
        bookmarks.append(
            Bookmark(title=str(item.title), page_num=page_num, children=children)
        )
    return bookmarks


def parse_outline_tree(pdf: pikepdf.Pdf) -> list[Bookmark]:
    """
    Parse the PDF outline into a tree of Bookmark objects.

    Returns list of top-level Bookmark objects, each with nested children.
    """
    try:
        with pdf.open_outline() as outline:
            return _parse_outline_items(pdf, outline.root)
    except Exception:
        return []


def get_top_level_bookmarks(bookmarks: list[Bookmark]) -> list[tuple[str, int]]:
    """
    Extract just the top-level bookmark info for splitting.

    Returns list of (title, page_number) tuples, sorted by page number.
    """
    result = [(b.title, b.page_num) for b in bookmarks]
    result.sort(key=lambda x: x[1])
    return result


def print_bookmark_tree(bookmark: Bookmark, indent: int = 0) -> None:
    """Print a bookmark and its children with indentation."""
    prefix = "  " * indent + ("- " if indent > 0 else "")
    print(f"    {prefix}{bookmark.title}")
    for child in bookmark.children:
        print_bookmark_tree(child, indent + 1)


def add_bookmarks_to_writer(
    pdf: pikepdf.Pdf,
    bookmark: Bookmark,
    start_page: int,
    end_page: int,
    parent=None,
) -> None:
    """
    Recursively add a bookmark and its children to the output PDF.

    Only includes bookmarks whose pages fall within the given range.
    Page numbers are adjusted relative to start_page.
    """
    if start_page <= bookmark.page_num <= end_page:
        adjusted_page = bookmark.page_num - start_page

        with pdf.open_outline() as outline:
            target = parent if parent is not None else outline.root
            item = pikepdf.OutlineItem(
                bookmark.title, adjusted_page
            )
            target.append(item)

            for child in bookmark.children:
                if start_page <= child.page_num <= end_page:
                    child_adjusted = child.page_num - start_page
                    child_item = pikepdf.OutlineItem(
                        child.title, child_adjusted
                    )
                    item.children.append(child_item)
                    # Recurse for deeper nesting
                    _add_children_recursive(
                        child.children, child_item, start_page, end_page
                    )


def _add_children_recursive(
    children: list[Bookmark],
    parent_item: pikepdf.OutlineItem,
    start_page: int,
    end_page: int,
) -> None:
    """Recursively add child bookmarks."""
    for child in children:
        if start_page <= child.page_num <= end_page:
            adjusted = child.page_num - start_page
            item = pikepdf.OutlineItem(child.title, adjusted)
            parent_item.children.append(item)
            _add_children_recursive(child.children, item, start_page, end_page)


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


def calculate_child_page_ranges(
    parent: Bookmark, parent_end_page: int
) -> list[tuple[str, int, int, Bookmark]]:
    """
    Calculate page ranges for each child bookmark within a parent's span.

    Returns list of (child_title, start_page, end_page, child_bookmark) tuples.
    end_page is inclusive.
    """
    if not parent.children:
        return []

    children_sorted = sorted(parent.children, key=lambda b: b.page_num)
    ranges = []

    for i, child in enumerate(children_sorted):
        start_page = child.page_num
        if i + 1 < len(children_sorted):
            end_page = children_sorted[i + 1].page_num - 1
        else:
            end_page = parent_end_page

        if end_page >= start_page:
            ranges.append((child.title, start_page, end_page, child))

    return ranges


def split_pdf(
    input_path: Path,
    output_dir: Path,
    verbose: int = 0,
    dry_run: bool = False,
    match: str | None = None,
    no_clobber: bool = False,
) -> int:
    """
    Split a PDF at top-level bookmarks into separate files.

    Args:
        verbose: Verbosity level (0=quiet, 1=progress, 2=include bookmark tree).
        match: If provided, only extract bookmarks containing this string (case-insensitive).
        no_clobber: If True, prepend 8-digit case number to output files that don't
            already contain one. Uses number from input filename, or starts at 00000000
            and increments until finding an unused filename.

    Returns the number of files created (or would be created in dry-run mode).
    """
    # Read the input PDF
    try:
        pdf = pikepdf.Pdf.open(input_path)
    except pikepdf.PdfError as e:
        print(f"Error: Cannot read PDF file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to open PDF: {e}", file=sys.stderr)
        sys.exit(1)

    total_pages = len(pdf.pages)
    if verbose >= 1:
        print(f"Opened {input_path.name} ({total_pages} pages)")

    # Parse full bookmark tree
    bookmark_tree = parse_outline_tree(pdf)

    if not bookmark_tree:
        print("Error: No top-level bookmarks found in PDF", file=sys.stderr)
        sys.exit(1)

    # Get top-level bookmarks for splitting
    top_level = get_top_level_bookmarks(bookmark_tree)

    if verbose >= 1:
        print(f"Found {len(top_level)} top-level bookmark(s)")

    # Calculate page ranges
    ranges = calculate_page_ranges(top_level, total_pages)

    # Filter by match string if provided
    # ranges_ext carries (title, start_page, end_page, child_bookmark_or_none)
    ranges_ext: list[tuple[str, int, int, Bookmark | None]] = [
        (t, s, e, None) for t, s, e in ranges
    ]
    if match:
        match_lower = match.lower()
        # Try top-level first
        filtered = [r for r in ranges_ext if match_lower in r[0].lower()]
        if filtered:
            if verbose >= 1:
                print(f"Filtered to {len(filtered)} top-level bookmark(s) matching '{match}'")
            ranges_ext = filtered
        else:
            # Fall back to second-level (child) bookmarks
            child_matches: list[tuple[str, int, int, Bookmark | None]] = []
            bookmark_by_title_tmp = {b.title: b for b in bookmark_tree}
            for title, start_page, end_page in ranges:
                parent_bm = bookmark_by_title_tmp.get(title)
                if not parent_bm or not parent_bm.children:
                    continue
                child_ranges = calculate_child_page_ranges(parent_bm, end_page)
                for child_title, cs, ce, child_bm in child_ranges:
                    if match_lower in child_title.lower():
                        if verbose >= 1:
                            print(f"Matched child bookmark '{child_title}' under '{title}'")
                        child_matches.append((child_title, cs, ce, child_bm))
            if not child_matches:
                print(f"Error: No bookmarks matching '{match}'", file=sys.stderr)
                sys.exit(1)
            if verbose >= 1:
                print(f"Filtered to {len(child_matches)} child bookmark(s) matching '{match}'")
            ranges_ext = child_matches

    # Create output directory if needed (unless dry-run)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Extract case number from input filename if using no-clobber
    base_case_number = None
    if no_clobber:
        base_case_number = extract_case_number(input_path.name)
        if base_case_number:
            if verbose >= 1:
                print(f"Using case number {base_case_number} from input filename")
        else:
            if verbose >= 1:
                print("No case number in input filename, will auto-generate if needed")

    # Track used filenames to handle duplicates
    used_names: set[str] = set()
    files_created = 0

    # Create a mapping from top-level title to its Bookmark object
    bookmark_by_title = {b.title: b for b in bookmark_tree}

    for title, start_page, end_page, child_bookmark in ranges_ext:
        # Generate safe filename
        safe_name = sanitize_filename(title)

        # Handle no-clobber: prepend case number if needed, check for existing files
        if no_clobber and not contains_case_number(safe_name):
            if base_case_number:
                # Use case number from input filename
                candidate_name = f"{base_case_number}_{safe_name}"
                output_path = get_unique_filename(output_dir, candidate_name, used_names)
            else:
                # No case number in input, find an unused number
                case_num = 0
                while True:
                    candidate_name = f"{case_num:08d}_{safe_name}"
                    output_path = output_dir / f"{candidate_name}.pdf"
                    if not output_path.exists() and candidate_name.lower() not in used_names:
                        used_names.add(candidate_name.lower())
                        break
                    case_num += 1
        else:
            output_path = get_unique_filename(output_dir, safe_name, used_names)

        page_count = end_page - start_page + 1

        if dry_run:
            print(f"Would create: {output_path.name}")
            print(f"  Pages {start_page + 1}-{end_page + 1} ({page_count} page(s))")
            print(f"  Bookmark: {title}")
            if verbose >= 2:
                if child_bookmark and child_bookmark.children:
                    print("  Bookmarks:")
                    for sub in child_bookmark.children:
                        print_bookmark_tree(sub, indent=1)
                elif title in bookmark_by_title:
                    print("  Bookmarks:")
                    print_bookmark_tree(bookmark_by_title[title])
        else:
            if verbose >= 1:
                print(f"Creating: {output_path.name}")
                print(f"  Pages {start_page + 1}-{end_page + 1} ({page_count} page(s))")
                if verbose >= 2:
                    if child_bookmark and child_bookmark.children:
                        print("  Bookmarks:")
                        for sub in child_bookmark.children:
                            print_bookmark_tree(sub, indent=1)
                    elif title in bookmark_by_title:
                        print("  Bookmarks:")
                        print_bookmark_tree(bookmark_by_title[title])

            # Create new PDF with the page range
            out_pdf = pikepdf.Pdf.new()
            for page_num in range(start_page, end_page + 1):
                out_pdf.pages.append(pdf.pages[page_num])

            # Remove resources not referenced by the included pages
            out_pdf.remove_unreferenced_resources()

            # Add bookmarks to output
            if child_bookmark:
                # Child match: add the child's sub-children as top-level bookmarks
                for sub in child_bookmark.children:
                    add_bookmarks_to_writer(
                        out_pdf, sub, start_page, end_page
                    )
            elif title in bookmark_by_title:
                # Top-level match: promote children to top level as before
                top_bookmark = bookmark_by_title[title]
                for child in top_bookmark.children:
                    add_bookmarks_to_writer(
                        out_pdf, child, start_page, end_page
                    )

            try:
                out_pdf.save(
                    output_path,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                )
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
        prog="splitmarks",
        description="Split a PDF file at top-level bookmarks into separate files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
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
        action="count",
        default=0,
        help="Increase verbosity (-v for progress, -vv for bookmark tree)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview splits without creating files",
    )
    parser.add_argument(
        "-m",
        "--match",
        type=str,
        help="Only extract bookmarks containing this string (case-insensitive)",
    )
    parser.add_argument(
        "--no-clobber",
        action="store_true",
        help="Avoid filename collisions by prepending case number from input filename, or auto-incrementing from 00000000",
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
        match=args.match,
        no_clobber=args.no_clobber,
    )

    # Summary
    action = "Would create" if args.dry_run else "Created"
    print(f"\n{action} {count} file(s)")


if __name__ == "__main__":
    main()
