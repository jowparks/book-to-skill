#!/usr/bin/env python3
"""Split paginated marker Markdown into page chunks for proofreading, and join
the corrected chunks back into one file.

Usage:
  marker_pages.py split <marker.md> <chunk-dir> [--pages N]
  marker_pages.py join <chunk-dir> <out.md>

marker_convert.sh runs marker with --paginate_output, which puts a
"{<page index>}------…" line before each page (0-based PDF page index).
`split` writes chunk-<first>-<last>.md files of N pages each (default 10),
keeping those markers so a proofreader can see page boundaries, and prints one
"<path>\t<first page>\t<last page>" line per chunk, with 1-based PDF pages.
`join` concatenates the chunks in page order and drops the markers.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PAGE_MARKER = re.compile(r"^\{(\d+)\}-{48}$", re.MULTILINE)
CHUNK_GLOB = "chunk-*.md"


def split(markdown: str, pages_per_chunk: int) -> list[tuple[int, int, str]]:
    """Return (first, last, text) per chunk; first/last are 1-based PDF pages."""
    markers = list(PAGE_MARKER.finditer(markdown))
    if not markers:
        raise ValueError("no page markers found; convert with marker_convert.sh (it paginates output)")
    preamble = markdown[: markers[0].start()]
    pages = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
        pages.append((int(m.group(1)) + 1, markdown[m.start() : end]))
    chunks = []
    for i in range(0, len(pages), pages_per_chunk):
        group = pages[i : i + pages_per_chunk]
        text = "".join(body for _, body in group)
        if i == 0:
            text = preamble + text
        chunks.append((group[0][0], group[-1][0], text))
    return chunks


def join(chunk_texts: list[str]) -> str:
    text = "".join(chunk_texts)
    text = PAGE_MARKER.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_split = sub.add_parser("split")
    p_split.add_argument("markdown", type=Path)
    p_split.add_argument("chunk_dir", type=Path)
    p_split.add_argument("--pages", type=int, default=10)
    p_join = sub.add_parser("join")
    p_join.add_argument("chunk_dir", type=Path)
    p_join.add_argument("out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "split":
        if args.pages < 1:
            parser.error("--pages must be at least 1")
        try:
            chunks = split(args.markdown.read_text(encoding="utf-8"), args.pages)
        except ValueError as exc:
            print(f"marker_pages: {exc}", file=sys.stderr)
            return 1
        args.chunk_dir.mkdir(parents=True, exist_ok=True)
        if any(args.chunk_dir.glob(CHUNK_GLOB)):
            print(f"marker_pages: {args.chunk_dir} already has chunks; use an empty directory", file=sys.stderr)
            return 1
        for first, last, text in chunks:
            path = args.chunk_dir / f"chunk-{first:05d}-{last:05d}.md"
            path.write_text(text, encoding="utf-8")
            print(f"{path}\t{first}\t{last}")
    else:
        paths = sorted(args.chunk_dir.glob(CHUNK_GLOB))
        if not paths:
            print(f"marker_pages: no chunks in {args.chunk_dir}", file=sys.stderr)
            return 1
        args.out.write_text(join([p.read_text(encoding="utf-8") for p in paths]), encoding="utf-8")
        print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
