"""scripts/marker_pages.py splits paginated marker Markdown into page chunks
for proofreading and joins the corrected chunks back without page markers."""

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = ROOT_DIR / "scripts" / "marker_pages.py"
SEP = "-" * 48


def paginated(page_indexes):
    # The shape marker's --paginate_output produces: 0-based page ids.
    return "".join(f"\n\n{{{i}}}{SEP}\n\nText of page {i + 1}.\n" for i in page_indexes)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def test_split_chunks_by_page_count_with_1_based_ranges(tmp_path):
    # Pages 4..26 (0-based 3..25), as from a --page_range run: 23 pages -> 10, 10, 3.
    md = tmp_path / "book.md"
    md.write_text("Preamble before first page.\n" + paginated(range(3, 26)))

    proc = run("split", md, tmp_path / "chunks")

    assert proc.returncode == 0, proc.stderr
    rows = [line.split("\t") for line in proc.stdout.splitlines()]
    assert [(r[1], r[2]) for r in rows] == [("4", "13"), ("14", "23"), ("24", "26")]
    first = Path(rows[0][0]).read_text()
    assert first.startswith("Preamble before first page.")
    assert "Text of page 13." in first and "Text of page 14." not in first
    assert f"{{3}}{SEP}" in first, "proofreaders need the page markers"


def test_join_keeps_corrections_in_page_order_and_drops_markers(tmp_path):
    md = tmp_path / "book.md"
    md.write_text(paginated(range(12)))
    chunk_dir = tmp_path / "chunks"
    run("split", md, chunk_dir, "--pages", "5")
    second = chunk_dir / "chunk-00006-00010.md"
    second.write_text(second.read_text().replace("Text of page 7.", "Corrected page 7."))

    out = tmp_path / "proofread.md"
    proc = run("join", chunk_dir, out)

    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert "Corrected page 7." in text and "Text of page 7." not in text
    order = [text.index(f"page {n}.") for n in range(1, 13)]
    assert order == sorted(order)
    assert SEP not in text


def test_split_rejects_unpaginated_markdown_and_reused_chunk_dir(tmp_path):
    plain = tmp_path / "plain.md"
    plain.write_text("# No page markers\n")
    assert run("split", plain, tmp_path / "a").returncode == 1

    md = tmp_path / "book.md"
    md.write_text(paginated(range(3)))
    assert run("split", md, tmp_path / "b").returncode == 0
    proc = run("split", md, tmp_path / "b")
    assert proc.returncode == 1 and "already has chunks" in proc.stderr
