# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**splitmarks** is a CLI tool that splits PDF files at top-level bookmarks into separate PDF files, named after their bookmark titles. Built for legal document processing (e.g., splitting memo packets into individual briefs/records).

## Development Commands

```bash
# Install in development mode
pip install -e .

# Run directly
python splitmarks.py <input.pdf> [options]

# Run as installed command
splitmarks <input.pdf> [options]

# Build standalone executable
pip install pyinstaller pikepdf
pyinstaller --onefile --name splitmarks splitmarks.py

# Manual testing with test documents (in test-docs/)
python splitmarks.py test-docs/example_memo_packet.pdf --dry-run -vv
python splitmarks.py test-docs/example_memo_packet.pdf -o /tmp/test-output -v
```

There is no automated test suite. Testing is done manually with PDFs in `test-docs/`.

## Architecture

Single-file tool: everything lives in `splitmarks.py` (no package structure).

**Pipeline:** Parse bookmarks → Filter (optional `--match`) → Calculate page ranges → Split into separate PDFs → Save with sanitized filenames

**Key components in `splitmarks.py`:**
- `Bookmark` dataclass — tree structure preserving PDF outline hierarchy
- `parse_outline_tree()` / `_parse_outline_items()` — recursive pikepdf outline parsing, handles both `/Dest` and `/A` (GoTo action) destinations
- `calculate_page_ranges()` — maps each top-level bookmark to its page span
- `split_pdf()` — main logic: open PDF, parse, filter, split, write output files
- `add_bookmarks_to_writer()` — promotes child bookmarks to top level in split output files
- `sanitize_filename()` / `get_unique_filename()` — safe filename generation with Unicode normalization, truncation, and deduplication
- `extract_case_number()` / `contains_case_number()` — 8-digit legal case number handling for `--no-clobber` mode
- `main()` — argparse CLI entry point

## Key Details

- **Python >= 3.10** required (uses `str | None` union syntax)
- **pikepdf** is the sole external dependency (migrated from pypdf for smaller output files via `remove_unreferenced_resources()` and `ObjectStreamMode.generate`)
- Version is tracked in **two places**: `__version__` in `splitmarks.py` and `version` in `pyproject.toml` — keep them in sync
- Entry point registered in pyproject.toml: `splitmarks = "splitmarks:main"`

## Release Process

1. Bump version in both `splitmarks.py` (`__version__`) and `pyproject.toml`
2. Commit, then tag with `v{version}` (e.g., `git tag v1.3.0`)
3. Push tag — GitHub Actions builds executables for Linux, macOS, and Windows via PyInstaller and uploads them to a GitHub Release

## macOS Binary Distribution

The macOS binary is ad-hoc signed in CI (`codesign --force --sign -`). This removes "damaged app" errors but does **not** satisfy Gatekeeper for downloaded files. Users who download the binary from GitHub Releases must remove the quarantine attribute before running it:

```bash
xattr -d com.apple.quarantine splitmarks-macos
chmod +x splitmarks-macos
```

Full Gatekeeper bypass (no quarantine removal needed) would require an Apple Developer ID certificate ($99/year) and notarization. Not currently set up.
