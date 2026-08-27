# splitmarks

Split a PDF file at top-level bookmarks into separate PDF files, named after each bookmark.

## Not an Official Court Product

An independent, open-source project published by an individual in a personal
capacity, consistent with Rule 3.1 of the North Dakota Code of Judicial Conduct.
It is a general-purpose PDF utility, not authorized, endorsed, or maintained by
any court.

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
splitmarks input.pdf [-o OUTPUT_DIR] [-m MATCH] [-v|-vv] [--dry-run] [--no-clobber] [--check-text] [--version]
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
| `--no-clobber` | Avoid collisions: prepend case number from filename, or auto-increment from 00000000 |
| `--check-text` | After splitting, warn about output PDFs whose text layer is missing or corrupt (needs `pdftotext`) |
| `--version` | Show version number and exit |

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

Split and flag any output that appears image-scanned (so you know what to OCR):

```bash
splitmarks packet.pdf -o ./split_output --check-text
```

Batch extract memos from multiple PDFs, avoiding filename collisions:

```bash
for f in ./packets/*.pdf; do
  splitmarks "$f" --match Memo --no-clobber -o ./memos
done
```

## How It Works

1. Opens the PDF and reads its bookmark outline
2. Splits at top-level bookmarks (each becomes a separate file)
3. Calculates page ranges for each section (from one bookmark to the next)
4. Creates a separate PDF file for each section, named after the bookmark title
5. Preserves nested bookmarks within each split file
6. Removes unreferenced resources (images, fonts) so each file contains only what its pages need

## Text-Layer Quality

`textquality.py` scores an extracted text layer and is the module `--check-text`
consults. It exists because character density alone answers the wrong question.
Density catches a pure image scan, but it is blind to a layer that is *present
and garbage* — the Acrobat "Paper Capture" and Google Books case, where a scan
yields plenty of characters of confident nonsense:

    "the assessmellt thereof shall Le suberdmate to the gelleral plall"

That matters because `ocrmypdf --skip-text` is a silent no-op on such a file: it
skips every page that already carries text, leaves the corruption in place, and
reports success. So three states are reported rather than two, each with a
different remedy:

| State | Meaning | Remedy |
|-------|---------|--------|
| `text-ok` | usable prose | use the text layer as-is |
| `no-text-layer` | image-only | `ocrmypdf --skip-text` |
| `text-layer-corrupt` | dense but wrong | `ocrmypdf --force-ocr` |

Thresholds are set against a measured corpus, not guessed; see the module
docstring for the signals and the reference numbers.

Usable as a library or on its own:

```bash
textquality FILE.pdf [FILE.pdf ...] [--json] [--quiet]
```

```python
from textquality import score_pdf, STATE_CORRUPT

r = score_pdf("scan.pdf")
if r["state"] == STATE_CORRUPT:
    subprocess.run(["ocrmypdf", *r["ocr_args"], src, dst])
```

`splitmarks.py` imports it optionally: a standalone copy of the script with no
`textquality.py` beside it keeps the older density-only behaviour rather than
failing.

## Filename Handling

Bookmark titles are sanitized for use as filenames:
- Spaces and unsafe characters (`/\:*?"<>|`) are replaced with hyphens
- Unicode is normalized
- Long names are truncated at word boundaries (max 200 chars)
- Duplicate names get a counter: `Title.pdf`, `Title-1.pdf`, `Title-2.pdf`
- With `--no-clobber`: case number prefix uses underscore: `12345678_Bench-Memo.pdf`

## Requirements

**Standalone executables**: No dependencies required.

**Install from source**: Python 3.10+ and pypdf >= 4.0.0

**`--check-text` only**: `pdftotext` (poppler) on `PATH`. If it is absent the check
degrades to "can't check, assume OK" rather than failing the run.

## Contributing

On a fresh clone, activate the local pre-push sensitive-content check:

```bash
git config --local core.hooksPath .githooks
```

It scans commits being pushed for likely ND court dockets, confidential-case
captions, and committed binaries. Bypass once with `git push --no-verify`.
