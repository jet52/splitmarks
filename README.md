# splitmarks

Split a PDF file at top-level bookmarks into separate PDF files, named after each bookmark.

## Installation

### Download (recommended)

Download the standalone executable for your platform from the [latest release](https://github.com/jet52/splitmarks/releases/latest):

- **Windows**: `splitmarks.exe`
- **macOS**: `splitmarks`
- **Linux**: `splitmarks`

On macOS/Linux, make it executable after downloading:
```bash
chmod +x splitmarks
```

### Install from source

Requires Python 3.10+:
```bash
pip install git+https://github.com/jet52/splitmarks.git
```

Or clone and install in development mode:
```bash
git clone https://github.com/jet52/splitmarks.git
cd splitmarks
pip install -e .
```

## Usage

```
splitmarks input.pdf [-o OUTPUT_DIR] [-m MATCH] [-v|-vv] [--dry-run]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `input_pdf` | PDF file to split |
| `-o, --output-dir DIR` | Output directory (default: current directory) |
| `-m, --match TEXT` | Only extract bookmarks containing TEXT (case-insensitive) |
| `-v` | Show progress (page counts, bookmark counts) |
| `-vv` | Also show nested bookmark tree for each output file |
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

Preview with full bookmark tree:

```bash
splitmarks document.pdf --dry-run -vv
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

**Standalone executables**: No dependencies required.

**Install from source**: Python 3.10+ and pypdf >= 4.0.0
