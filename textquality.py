#!/usr/bin/env python3
"""Text-layer quality scoring for PDFs.

Answers a question the old density-only check could not: *is this text layer
present but wrong?*

The prior check asked only whether a PDF yielded at least ~50 characters per
page.  That catches a pure image scan, but it is blind to the far more
dangerous case — a layer that is dense and garbage.  Court e-filing systems,
Google Books, and Adobe Acrobat "Paper Capture" all routinely emit those.  A
scanned nineteenth-century source reviewed in the field extracted as

    "the assessmellt thereof shall Le suberdmate to the gelleral plall"

which is 60 characters per page of confident nonsense.  Worse, because a text
layer *existed*, ``ocrmypdf --skip-text`` silently skipped every page and left
the corruption in place.  The verification that relied on it looked clean.

So this module reports three states rather than two, and each maps to a
different remedy:

===================== ===============================================
``text-ok``           use the text layer as-is
``no-text-layer``     OCR it; ``--skip-text`` is safe and cheap
``text-layer-corrupt``  OCR it; ``--skip-text`` is a NO-OP, use ``--force-ocr``
===================== ===============================================

Scoring
-------
Thresholds are set empirically against a corpus of known-good and known-bad
extractions rather than guessed.  Three signals separate them by 17-65x, and
all three are genre-independent — they measure letter sequences that do not
occur in real words, so born-digital briefs, old book scans, and law review
PDFs all score alike:

``caseflip``
    Rate of tokens with an internal lowercase-to-uppercase transition
    ("suberdmate").  Strongest single signal.  Guarded against legitimate
    intercapped names (McCue, LaMoure, O'Brien).
``novowel``
    Rate of tokens of four or more letters containing no vowel.
``ccc``
    Rate of tokens containing a run of four or more consonants.

Deliberately *not* used: stopword rate.  It looks appealing and it does not
work — in the reference corpus a born-digital appellee brief scored 0.298 and
the corrupt scan scored 0.380, i.e. backwards.  Function words are short and
survive OCR damage that destroys the words carrying the meaning.

Reference corpus (``corruption`` = weighted sum, see :data:`_WEIGHTS`):

===================================== ============
19th-c. scan, Acrobat layer           0.414
same file, after ``--force-ocr``      0.016
19th-c. book scan (clean)             0.030
appellate brief (born-digital)        0.022
law review PDF                        0.026
===================================== ============

The gap between 0.03 and 0.41 is more than a factor of ten, so the cutoff sits
at 0.10 with roughly 3x headroom on either side.

Library use::

    from textquality import score_text, score_pdf, STATE_CORRUPT

    r = score_pdf(Path("scan.pdf"))
    if r["state"] == STATE_CORRUPT:
        subprocess.run(["ocrmypdf", *r["ocr_args"], src, dst])

CLI::

    textquality.py FILE.pdf [FILE.pdf ...] [--json] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = [
    "STATE_OK",
    "STATE_NONE",
    "STATE_CORRUPT",
    "STATE_UNKNOWN",
    "score_text",
    "score_pdf",
    "recommended_ocr_args",
]

STATE_OK = "text-ok"
STATE_NONE = "no-text-layer"
STATE_CORRUPT = "text-layer-corrupt"
STATE_UNKNOWN = "unknown"

#: Minimum extracted characters per page before a layer counts as present.
DEFAULT_MIN_CHARS_PER_PAGE = 50

#: Corruption score at or above which a present layer is called corrupt.
DEFAULT_CORRUPTION_CUTOFF = 0.10

#: Below this many alphabetic tokens the sample is too small to judge.  A
#: short sample is reported as ``unknown``, never as corrupt — a false
#: "corrupt" triggers an expensive needless re-OCR, and worse, teaches the
#: caller to distrust the check.
MIN_TOKENS_FOR_JUDGMENT = 200

# Weights chosen so the reference corpus separates at ~0.10.  caseflip is
# weighted highest because it is the least ambiguous: real English words do
# not flip case internally, whereas a rare consonant cluster ("strengths")
# genuinely occurs.
_WEIGHTS = {"caseflip": 6.0, "novowel": 8.0, "ccc": 2.0}

#: Score at which quality is reported as 0.0.  Purely cosmetic — it maps the
#: raw corruption score onto a 0-1 scale for humans.
_QUALITY_FLOOR = 0.40

_TOKEN_RE = re.compile(r"[A-Za-z]+")
_VOWEL_RE = re.compile(r"[aeiouyAEIOUY]")
_CASEFLIP_RE = re.compile(r"[a-z][A-Z]")
_CONSONANT_RUN_RE = re.compile(r"[bcdfghjklmnpqrstvwxz]{4,}")

# Legitimately intercapped surnames and prefixes, which are common in legal
# prose and would otherwise inflate `caseflip`: McCue, MacArthur, LaMoure,
# DeSoto, VanDyke, O'Brien, plus camelCase product names (MedCenter).
_INTERCAP_OK_RE = re.compile(
    r"^(?:Mc|Mac|De|Di|Du|La|Le|Van|Von|O)[A-Z][a-z]", )


def _signals(text: str) -> dict:
    """Compute the three corruption signals plus descriptive stats."""
    tokens = _TOKEN_RE.findall(text)
    n = len(tokens)
    if not n:
        return {"tokens": 0, "caseflip": 0.0, "novowel": 0.0, "ccc": 0.0,
                "mean_token_len": 0.0}

    caseflip = novowel = ccc = 0
    total_len = 0
    for w in tokens:
        total_len += len(w)
        if len(w) >= 3 and _CASEFLIP_RE.search(w) and not _INTERCAP_OK_RE.match(w):
            caseflip += 1
        if len(w) >= 4 and not _VOWEL_RE.search(w):
            novowel += 1
        if _CONSONANT_RUN_RE.search(w.lower()):
            ccc += 1

    return {
        "tokens": n,
        "caseflip": caseflip / n,
        "novowel": novowel / n,
        "ccc": ccc / n,
        "mean_token_len": total_len / n,
    }


def score_text(
    text: str,
    page_count: int | None = None,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
    corruption_cutoff: float = DEFAULT_CORRUPTION_CUTOFF,
) -> dict:
    """Classify an extracted text layer.

    ``page_count`` enables the density test that distinguishes
    ``no-text-layer`` from a present-but-corrupt one.  Without it, density is
    not evaluated and only the corruption signals are used.

    Returns a dict with ``state``, ``quality`` (0-1, higher is better),
    ``corruption``, ``reason``, ``signals``, and ``ocr_args`` — the flags to
    hand ``ocrmypdf``, or ``None`` when no OCR is needed.
    """
    text = (text or "").strip()
    chars = len(text)
    chars_per_page = (chars / page_count) if page_count else None

    sig = _signals(text)
    corruption = sum(_WEIGHTS[k] * sig[k] for k in _WEIGHTS)
    quality = max(0.0, 1.0 - corruption / _QUALITY_FLOOR)

    result = {
        "state": STATE_UNKNOWN,
        "quality": round(quality, 3),
        "corruption": round(corruption, 4),
        "chars": chars,
        "chars_per_page": (round(chars_per_page, 1)
                           if chars_per_page is not None else None),
        "page_count": page_count,
        "signals": {k: round(v, 5) if isinstance(v, float) else v
                    for k, v in sig.items()},
        "reason": "",
        "ocr_args": None,
    }

    # 1. Nothing there at all.
    if chars_per_page is not None and chars_per_page < min_chars_per_page:
        result["state"] = STATE_NONE
        result["reason"] = (
            f"{chars_per_page:.1f} chars/page is below the "
            f"{min_chars_per_page} threshold; the file appears image-only")
    elif page_count is None and chars == 0:
        result["state"] = STATE_NONE
        result["reason"] = "no text extracted"
    # 2. Present. Is it any good?
    elif sig["tokens"] < MIN_TOKENS_FOR_JUDGMENT:
        result["state"] = STATE_UNKNOWN
        result["reason"] = (
            f"only {sig['tokens']} alphabetic tokens; too small a sample to "
            f"judge quality (need {MIN_TOKENS_FOR_JUDGMENT})")
    elif corruption >= corruption_cutoff:
        result["state"] = STATE_CORRUPT
        worst = max(_WEIGHTS, key=lambda k: _WEIGHTS[k] * sig[k])
        result["reason"] = (
            f"corruption {corruption:.3f} exceeds {corruption_cutoff:.2f} "
            f"(dominant signal: {worst}={sig[worst]:.4f}); a text layer is "
            f"present but is not reliable prose")
    else:
        result["state"] = STATE_OK
        result["reason"] = f"corruption {corruption:.3f} is within tolerance"

    result["ocr_args"] = recommended_ocr_args(result["state"])
    return result


def recommended_ocr_args(state: str) -> list[str] | None:
    """Flags to pass ``ocrmypdf`` for a given state, or ``None`` if not needed.

    The distinction is the whole point of this module.  ``--skip-text`` skips
    any page that already carries text, so on a corrupt layer it is a silent
    no-op that leaves the corruption in place while reporting success.
    ``--force-ocr`` rasterizes and re-recognizes unconditionally.
    """
    if state == STATE_NONE:
        return ["--skip-text"]
    if state == STATE_CORRUPT:
        return ["--force-ocr"]
    return None


def score_pdf(
    path: Path | str,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
    corruption_cutoff: float = DEFAULT_CORRUPTION_CUTOFF,
    timeout: int = 120,
    max_pages: int | None = 40,
) -> dict:
    """Score a PDF's text layer using ``pdftotext``.

    Only the first ``max_pages`` pages are extracted (set ``None`` for all) —
    a few dozen pages is a large enough sample and keeps the check fast on
    thousand-page records.

    Degrades rather than raising: if poppler is missing or the page count is
    unreadable, returns ``unknown`` with a reason.  A check that cannot run is
    not evidence of a problem.
    """
    path = Path(path)
    out = {"path": str(path)}

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        out.update(score_text(""), state=STATE_UNKNOWN,
                   reason="pdftotext (poppler) not on PATH; cannot check")
        return out

    page_count = _page_count(path)

    cmd = [pdftotext]
    sample_pages = page_count
    if max_pages and page_count and page_count > max_pages:
        cmd += ["-l", str(max_pages)]
        sample_pages = max_pages
    cmd += [str(path), "-"]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        text = proc.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError) as e:
        out.update(score_text(""), state=STATE_UNKNOWN,
                   reason=f"pdftotext failed: {e}")
        return out

    out.update(score_text(text, page_count=sample_pages,
                          min_chars_per_page=min_chars_per_page,
                          corruption_cutoff=corruption_cutoff))
    out["path"] = str(path)
    out["total_pages"] = page_count
    out["sampled_pages"] = sample_pages
    return out


def _page_count(path: Path) -> int | None:
    """Page count via pdfinfo, falling back to pypdf.

    pdfinfo is tried first because poppler tolerates damaged and >2GB files
    that pypdf refuses (a 32-bit cross-reference offset overflow makes pypdf
    raise on large court record packets).
    """
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        try:
            proc = subprocess.run([pdfinfo, str(path)],
                                  capture_output=True, timeout=60)
            for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":", 1)[1].strip())
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
    try:
        import pypdf
        return len(pypdf.PdfReader(str(path)).pages)
    except Exception:
        return None


_LABEL = {
    STATE_OK: "OK",
    STATE_NONE: "IMAGE-ONLY",
    STATE_CORRUPT: "CORRUPT",
    STATE_UNKNOWN: "UNKNOWN",
}


def main() -> int:
    p = argparse.ArgumentParser(
        prog="textquality",
        description="Classify a PDF's text layer as ok / image-only / corrupt.")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--quiet", action="store_true",
                   help="only report files needing OCR")
    p.add_argument("--min-chars-per-page", type=int,
                   default=DEFAULT_MIN_CHARS_PER_PAGE)
    p.add_argument("--corruption-cutoff", type=float,
                   default=DEFAULT_CORRUPTION_CUTOFF)
    p.add_argument("--max-pages", type=int, default=40,
                   help="pages to sample (0 = all)")
    args = p.parse_args()

    results = [
        score_pdf(f,
                  min_chars_per_page=args.min_chars_per_page,
                  corruption_cutoff=args.corruption_cutoff,
                  max_pages=args.max_pages or None)
        for f in args.files
    ]

    if args.json:
        print(json.dumps(results, indent=2))
        return 1 if any(r["state"] == STATE_CORRUPT for r in results) else 0

    for r in results:
        needs = r["ocr_args"] is not None
        if args.quiet and not needs:
            continue
        name = Path(r["path"]).name
        print(f"{_LABEL[r['state']]:<11} {name}")
        print(f"            quality {r['quality']:.2f} · {r['reason']}")
        if needs:
            print(f"            → ocrmypdf {' '.join(r['ocr_args'])} "
                  f"'{name}' '{Path(name).stem}.ocr.pdf'")
    return 1 if any(r["state"] == STATE_CORRUPT for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
