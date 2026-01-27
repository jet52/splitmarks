# packetsplitter

Split a PDF file at top-level bookmarks into separate PDF files, named after each bookmark.

## Installation

```bash
pip install -e .
```

## Usage

```
packetsplitter input.pdf [-o OUTPUT_DIR] [-v] [--dry-run]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `input_pdf` | PDF file to split |
| `-o, --output-dir DIR` | Output directory (default: current directory) |
| `-v, --verbose` | Show detailed progress |
| `--dry-run` | Preview splits without creating files |

### Examples

Preview what files would be created:

```bash
packetsplitter document.pdf --dry-run
```

Split a PDF into the current directory:

```bash
packetsplitter document.pdf
```

Split into a specific directory with verbose output:

```bash
packetsplitter document.pdf -o ./split_files -v
```

## How It Works

1. Opens the PDF and reads its bookmark outline
2. Extracts only top-level bookmarks (nested bookmarks are ignored)
3. Calculates page ranges for each section (from one bookmark to the next)
4. Creates a separate PDF file for each section, named after the bookmark title

## Filename Handling

Bookmark titles are sanitized for use as filenames:
- Unsafe characters (`/\:*?"<>|`) are replaced with underscores
- Unicode is normalized
- Whitespace is collapsed
- Long names are truncated at word boundaries (max 200 chars)
- Duplicate names get a counter: `title.pdf`, `title (1).pdf`, etc.

## Requirements

- Python 3.10+
- pypdf >= 4.0.0
