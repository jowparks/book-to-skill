"""scripts/marker_convert.sh converts a PDF with marker in page chunks that a
rerun resumes, runs marker without its LLM pass (no API key), joins chunks
back into one file, and can install marker into a private venv. A fake
`marker_single` records its calls and writes paginated output for the
requested page range; a fake `pypdfium2` reports the page count.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = ROOT_DIR / "scripts" / "marker_convert.sh"
SEP = "-" * 48

FAKE_MARKER = """#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_MARKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
first, last = map(int, args[args.index("--page_range") + 1].split("-"))
if str(first) == os.environ.get("FAKE_MARKER_FAIL_AT"):
    sys.exit(1)  # crash before writing anything, like an interrupted run
stem = Path(args[0]).stem
out = Path(args[args.index("--output_dir") + 1]) / stem
out.mkdir(parents=True)
(out / (stem + ".md")).write_text("".join(
    "\\n\\n{{%d}}%s\\n\\nText of page %d.\\n\\n![](_page_%d_Figure_1.jpeg)\\n" % (i, "-" * 48, i + 1, i)
    for i in range(first, last + 1)))
for i in range(first, last + 1):
    (out / ("_page_%d_Figure_1.jpeg" % i)).write_bytes(b"jpeg")
(out / (stem + "_meta.json")).write_text("{{}}")
"""

FAKE_PYPDFIUM2 = """import os
class PdfDocument:
    def __init__(self, path):
        pass
    def __len__(self):
        return int(os.environ["FAKE_PAGES"])
"""

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash script")


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = bin_dir / "marker_single"
    marker.write_text(FAKE_MARKER.format(python=sys.executable))
    marker.chmod(0o755)
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "pypdfium2.py").write_text(FAKE_PYPDFIUM2)
    return {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "PYTHONPATH": str(lib),
        "TMPDIR": str(tmp_path),
        "FAKE_MARKER_LOG": str(tmp_path / "calls.jsonl"),
        "MARKER_VENV": str(tmp_path / "venv"),
        "FAKE_PAGES": "23",
    }


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "my book.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    return path


def run(env, *args, **extra):
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, args)],
        env={**env, **extra},
        capture_output=True,
        text=True,
        start_new_session=True,
    )


def calls(env):
    log = Path(env["FAKE_MARKER_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def page_ranges(env):
    return [c[c.index("--page_range") + 1] for c in calls(env)]


def test_converts_in_10_page_chunks_without_llm_pass(env, pdf, tmp_path):
    out = tmp_path / "chunks"
    proc = run(env, pdf, out)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == str(out)
    assert page_ranges(env) == ["0-9", "10-19", "20-22"]
    for argv in calls(env):
        assert "--force_ocr" in argv and "--paginate_output" in argv
        assert "--use_llm" not in argv
    assert sorted(p.name for p in out.glob("chunk-*.md")) == [
        "chunk-00001-00010.md", "chunk-00011-00020.md", "chunk-00021-00023.md"]
    last = (out / "chunk-00021-00023.md").read_text()
    assert f"{{20}}{SEP}" in last and "Text of page 23." in last and "Text of page 20." not in last
    assert (out / "_page_22_Figure_1.jpeg").exists(), "figures must sit beside the chunks"
    assert not list(out.glob(".work.*"))


def test_rerun_resumes_after_an_interrupted_chunk(env, pdf, tmp_path):
    out = tmp_path / "chunks"
    proc = run(env, pdf, out, FAKE_MARKER_FAIL_AT="10")
    assert proc.returncode != 0
    assert [p.name for p in out.glob("chunk-*.md")] == ["chunk-00001-00010.md"]

    Path(env["FAKE_MARKER_LOG"]).unlink()
    proc = run(env, pdf, out)

    assert proc.returncode == 0, proc.stderr
    assert page_ranges(env) == ["10-19", "20-22"], "finished chunks must not be redone"
    assert len(list(out.glob("chunk-*.md"))) == 3


def test_sample_chunks_are_reused_by_the_full_run(env, pdf, tmp_path):
    out = tmp_path / "chunks"
    proc = run(env, "--sample", pdf, out, FAKE_PAGES="95", MARKER_CHUNK_PAGES="7")
    assert proc.returncode == 0, proc.stderr
    # 30 sample pages rounded up to whole 7-page chunks: 35 pages.
    assert page_ranges(env) == ["0-6", "7-13", "14-20", "21-27", "28-34"]

    Path(env["FAKE_MARKER_LOG"]).unlink()
    proc = run(env, pdf, out, FAKE_PAGES="95", MARKER_CHUNK_PAGES="7")

    assert proc.returncode == 0, proc.stderr
    assert page_ranges(env)[0] == "35-41"


def test_join_concatenates_chunks_in_page_order_without_markers(env, pdf, tmp_path):
    out = tmp_path / "chunks"
    run(env, pdf, out)
    second = out / "chunk-00011-00020.md"
    second.write_text(second.read_text().replace("Text of page 12.", "Corrected page 12."))

    joined = tmp_path / "book.md"
    proc = run(env, "--join", out, joined)

    assert proc.returncode == 0, proc.stderr
    text = joined.read_text()
    assert "Corrected page 12." in text and "Text of page 12." not in text
    order = [text.index(f"page {n}.") for n in range(1, 24)]
    assert order == sorted(order)
    assert SEP not in text
    assert "\n\n\n" not in text


def test_missing_marker_exits_2_and_points_at_install(env, pdf, tmp_path):
    (Path(env["PATH"].split(os.pathsep)[0]) / "marker_single").unlink()
    proc = run(env, pdf, tmp_path / "chunks")

    assert proc.returncode == 2
    assert "--install" in proc.stderr
    assert calls(env) == []


# Stands in for a Python >= 3.10 interpreter (or one too old, if
# FAKE_PYTHON_TOO_OLD is set): `-m venv DIR` copies itself to DIR/bin/python,
# and `-m pip install marker-pdf` drops the fake marker_single beside itself.
FAKE_PYTHON = """#!{python}
import os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "-c":
    sys.exit(1 if os.environ.get("FAKE_PYTHON_TOO_OLD") else 0)
if args[:2] == ["-m", "venv"]:
    bin_dir = Path(args[2]) / "bin"
    bin_dir.mkdir(parents=True)
    shutil.copy(__file__, bin_dir / "python")
elif args[:4] == ["-m", "pip", "install", "marker-pdf"]:
    marker = Path(__file__).parent / "marker_single"
    marker.write_text({marker!r})
    marker.chmod(0o755)
"""


@pytest.fixture
def fake_python(tmp_path):
    py = tmp_path / "py" / "fake-python"
    py.parent.mkdir()
    py.write_text(FAKE_PYTHON.format(python=sys.executable, marker=FAKE_MARKER.format(python=sys.executable)))
    py.chmod(0o755)
    return str(py)


def test_install_creates_venv_that_later_runs_use(env, pdf, tmp_path, fake_python):
    (Path(env["PATH"].split(os.pathsep)[0]) / "marker_single").unlink()
    proc = run(env, "--install", MARKER_PYTHON=fake_python)

    venv_marker = tmp_path / "venv" / "bin" / "marker_single"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == str(venv_marker)

    proc = run(env, pdf, tmp_path / "chunks")
    assert proc.returncode == 0, proc.stderr
    assert len(calls(env)) == 3, "conversion did not use the venv's marker_single"


def test_install_refuses_python_older_than_3_10(env, tmp_path, fake_python):
    proc = run(env, "--install", MARKER_PYTHON=fake_python, FAKE_PYTHON_TOO_OLD="1")

    assert proc.returncode == 4
    assert not (tmp_path / "venv").exists()
