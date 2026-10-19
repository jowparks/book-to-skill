#!/usr/bin/env bash
# Convert a PDF to Markdown with marker (OCR, equations as LaTeX) before
# book-to-skill extraction. Marker is a separate tool, not a book-to-skill
# dependency. Its LLM pass is off: the agent proofreads the output instead
# (SKILL.md Step 1.6), so no API key is needed.
#
# Usage: marker_convert.sh [--sample] <file.pdf> <output-dir>
#        marker_convert.sh --install
#
# marker_single is taken from PATH, else from a private venv at MARKER_VENV
# (default ~/.cache/book-to-skill/marker-venv). --install creates that venv
# with the first Python >= 3.10 found (MARKER_PYTHON overrides the search)
# and installs marker-pdf into it; it prints the marker_single path.
#
# Output is paginated ("{<page index>}----" before each page) so
# marker_pages.py can split it for proofreading. --sample converts only the
# first pages so the output can be checked before a full run.
#
# On success the last line of stdout is the path of the generated Markdown.
set -euo pipefail

SAMPLE_PAGES="0-30"

die() { printf 'marker_convert: %s\n' "$2" >&2; exit "$1"; }

MARKER_VENV=${MARKER_VENV:-${XDG_CACHE_HOME:-$HOME/.cache}/book-to-skill/marker-venv}

find_python() {
  local py
  for py in ${MARKER_PYTHON:-python3.12 python3.11 python3.13 python3.10 python3}; do
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      printf '%s\n' "$py"
      return 0
    fi
  done
  return 1
}

if [ "${1:-}" = "--install" ]; then
  [ $# -eq 1 ] || die 64 "usage: marker_convert.sh --install"
  if [ ! -x "$MARKER_VENV/bin/marker_single" ]; then
    py=$(find_python) ||
      die 4 "marker needs Python >= 3.10; install one (e.g. brew install python@3.12) or set MARKER_PYTHON"
    printf 'marker_convert: installing marker-pdf into %s with %s\n' "$MARKER_VENV" "$py" >&2
    "$py" -m venv "$MARKER_VENV"
    "$MARKER_VENV/bin/python" -m pip install marker-pdf >&2
  fi
  [ -x "$MARKER_VENV/bin/marker_single" ] || die 1 "install finished but $MARKER_VENV/bin/marker_single is missing"
  printf '%s\n' "$MARKER_VENV/bin/marker_single"
  exit 0
fi

sample=false
if [ "${1:-}" = "--sample" ]; then sample=true; shift; fi
[ $# -eq 2 ] || die 64 "usage: marker_convert.sh [--sample] <file.pdf> <output-dir>"
pdf=$1
out_dir=$2
[ -f "$pdf" ] || die 66 "not a file: $pdf"

if command -v marker_single >/dev/null 2>&1; then
  marker=marker_single
elif [ -x "$MARKER_VENV/bin/marker_single" ]; then
  marker=$MARKER_VENV/bin/marker_single
else
  die 2 "marker_single not found; install it with: marker_convert.sh --install"
fi

# --force_ocr: trusting a PDF's text layer drops most prose on scans whose only
# text is a watermark, and OCR gets equations right far more often.
args=(--force_ocr --output_format markdown --paginate_output --output_dir "$out_dir")
if $sample; then args+=(--page_range "$SAMPLE_PAGES"); fi

printf 'marker_convert: %s%s\n' "$pdf" "$($sample && printf ' (sample pages %s)' "$SAMPLE_PAGES")" >&2
"$marker" "$pdf" "${args[@]}" >&2

stem=$(basename "$pdf")
stem=${stem%.*}
md="$out_dir/$stem/$stem.md"
[ -f "$md" ] || die 1 "marker finished but $md was not created"
printf '%s\n' "$md"
