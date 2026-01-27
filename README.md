# splitmarks

Split a PDF file at top-level bookmarks into separate PDF files, named after each bookmark.

## Installation

```bash
pip install -e .
```

## Usage

```
splitmarks input.pdf [-o OUTPUT_DIR] [-m MATCH] [-v] [--dry-run]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `input_pdf` | PDF file to split |
| `-o, --output-dir DIR` | Output directory (default: current directory) |
| `-m, --match TEXT` | Only extract bookmarks containing TEXT (case-insensitive) |
| `-v, --verbose` | Show detailed progress |
| `--dry-run` | Preview splits without creating files |

### Examples

Preview what files would be created:

```bash
splitmarks document.pdf --dry-run
```

Split a PDF into the current directory:

```bash
splitmarks document.pdf
```

Split into a specific directory with verbose output:

```bash
splitmarks document.pdf -o ./split_files -v
```

Extract only bookmarks containing "Memo":

```bash
splitmarks document.pdf --match Memo
```

Extract all briefs (case-insensitive matching):

```bash
splitmarks document.pdf -m brief -o ./briefs
```

## How It Works

1. Opens the PDF and reads its bookmark outline
2. Splits at top-level bookmarks (each becomes a separate file)
3. Calculates page ranges for each section (from one bookmark to the next)
4. Creates a separate PDF file for each section, named after the bookmark title
5. Preserves nested bookmarks within each split file

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
