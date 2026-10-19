#!/usr/bin/env bash
# Convert a PDF to Markdown with marker (OCR, equations as LaTeX) before
# book-to-skill extraction. Marker is a separate tool, not a book-to-skill
# dependency. Its LLM pass is off: the agent proofreads the output instead
# (SKILL.md Step 1.6), so no API key is needed.
#
# Usage: marker_convert.sh [--sample] <file.pdf> <chunk-dir>
#        marker_convert.sh --join <chunk-dir> <out.md>
#        marker_convert.sh --install
#
# The PDF is converted in chunks of MARKER_CHUNK_PAGES pages (default 10),
# one marker run each, written to <chunk-dir>/chunk-<first>-<last>.md
# (1-based PDF pages) with figures beside them. A chunk is written only once
# complete, and existing chunks are skipped, so an interrupted run resumes
# where it stopped. Each page starts with a "{<0-based page index>}----"
# marker line. --sample converts only the first 30 pages, as chunks a later
# full run into the same directory reuses. On success the last line of
# stdout is <chunk-dir>.
#
# --join concatenates the chunks in page order without the page markers.
#
# marker_single is taken from PATH, else from a private venv at MARKER_VENV
# (default ~/.cache/book-to-skill/marker-venv). --install creates that venv
# with the first Python >= 3.10 found (MARKER_PYTHON overrides the search)
# and installs marker-pdf into it; it prints the marker_single path.
set -euo pipefail

SAMPLE_PAGES=30
CHUNK_PAGES=${MARKER_CHUNK_PAGES:-10}
PAGE_MARKER='^\{[0-9]+\}-{48}$'

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

if [ "${1:-}" = "--join" ]; then
  [ $# -eq 3 ] || die 64 "usage: marker_convert.sh --join <chunk-dir> <out.md>"
  chunks=("$2"/chunk-*.md)
  [ -f "${chunks[0]}" ] || die 66 "no chunks in $2"
  # Glob order is page order: chunk names use zero-padded page numbers.
  cat "${chunks[@]}" | grep -Ev "$PAGE_MARKER" | cat -s >"$3"
  printf '%s\n' "$3"
  exit 0
fi

sample=false
if [ "${1:-}" = "--sample" ]; then sample=true; shift; fi
[ $# -eq 2 ] || die 64 "usage: marker_convert.sh [--sample] <file.pdf> <chunk-dir>"
pdf=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
out_dir=$2
[ -f "$pdf" ] || die 66 "not a file: $1"

if command -v marker_single >/dev/null 2>&1; then
  marker=$(command -v marker_single)
elif [ -x "$MARKER_VENV/bin/marker_single" ]; then
  marker=$MARKER_VENV/bin/marker_single
else
  die 2 "marker_single not found; install it with: marker_convert.sh --install"
fi

# Count pages with marker's own interpreter (marker depends on pypdfium2).
# Run from / so a planted module in the caller's directory is never imported.
py=$(head -1 "$marker" | sed -n 's/^#! *//p')
pages=$(cd / && $py -c 'import sys, pypdfium2; print(len(pypdfium2.PdfDocument(sys.argv[1])))' "$pdf") ||
  die 1 "could not count the pages of $pdf"
# The sample ends on a chunk boundary so a later full run reuses its chunks.
sample_pages=$(( (SAMPLE_PAGES + CHUNK_PAGES - 1) / CHUNK_PAGES * CHUNK_PAGES ))
if $sample && [ "$pages" -gt "$sample_pages" ]; then pages=$sample_pages; fi

mkdir -p "$out_dir"
rm -rf "$out_dir"/.work.*  # left by an interrupted run
stem=$(basename "$pdf")
stem=${stem%.*}
total=$(( (pages + CHUNK_PAGES - 1) / CHUNK_PAGES ))
n=0
for (( first = 1; first <= pages; first += CHUNK_PAGES )); do
  n=$((n + 1))
  last=$(( first + CHUNK_PAGES - 1 ))
  if [ "$last" -gt "$pages" ]; then last=$pages; fi
  chunk=$(printf '%s/chunk-%05d-%05d.md' "$out_dir" "$first" "$last")
  if [ -f "$chunk" ]; then
    printf 'marker_convert: chunk %d/%d (pages %d-%d) already done\n' "$n" "$total" "$first" "$last" >&2
    continue
  fi
  work=$(mktemp -d "$out_dir/.work.XXXXXX")
  # --force_ocr: trusting a PDF's text layer drops most prose on scans whose
  # only text is a watermark, and OCR gets equations right far more often.
  "$marker" "$pdf" --force_ocr --output_format markdown --paginate_output \
    --page_range "$((first - 1))-$((last - 1))" --output_dir "$work" >&2
  [ -f "$work/$stem/$stem.md" ] || die 1 "marker finished but wrote no Markdown for pages $first-$last"
  find "$work/$stem" -type f ! -name "$stem.md" ! -name "${stem}_meta.json" -exec mv {} "$out_dir/" \;
  mv "$work/$stem/$stem.md" "$chunk"
  rm -rf "$work"
  printf 'marker_convert: chunk %d/%d (pages %d-%d) done\n' "$n" "$total" "$first" "$last" >&2
done
printf '%s\n' "$out_dir"
