"""scripts/marker_convert.sh runs marker without its LLM pass (no API key)
and with paginated output, and can install marker into a private venv. A fake
`marker_single` records what it was called with.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = ROOT_DIR / "scripts" / "marker_convert.sh"

FAKE_MARKER = """#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("--output_dir") + 1])
stem = Path(args[0]).stem
(out / stem).mkdir(parents=True)
(out / stem / (stem + ".md")).write_text("# Converted\\n")
Path(os.environ["FAKE_MARKER_LOG"]).write_text(json.dumps({{"argv": args}}))
"""

# Stands in for a Python >= 3.10 interpreter (or one too old, if
# FAKE_PYTHON_TOO_OLD is set): `-m venv DIR` copies itself to DIR/bin/python,
# and `-m pip install marker-pdf` drops a fake marker_single beside itself.
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

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash script")


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "marker_single"
    fake.write_text(FAKE_MARKER.format(python=sys.executable))
    fake.chmod(0o755)
    pdf = tmp_path / "my book.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    log = tmp_path / "marker.json"

    def _run(*flags, marker_on_path=True, **keys):
        if not marker_on_path:
            fake.unlink(missing_ok=True)
        env = {
            "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "TMPDIR": str(tmp_path),
            "FAKE_MARKER_LOG": str(log),
            "MARKER_VENV": str(tmp_path / "venv"),
            **keys,
        }
        paths = [] if "--install" in flags else [str(pdf), str(tmp_path / "out")]
        proc = subprocess.run(
            ["bash", str(SCRIPT), *flags, *paths],
            env=env,
            capture_output=True,
            text=True,
            start_new_session=True,  # no controlling terminal, so no prompt
        )
        record = json.loads(log.read_text()) if log.exists() else None
        return proc, record

    return _run


def test_converts_without_llm_pass_or_api_key(run, tmp_path):
    proc, record = run()  # no key in the environment, no terminal

    assert proc.returncode == 0, proc.stderr
    argv = record["argv"]
    assert "--use_llm" not in argv
    assert "--force_ocr" in argv
    assert "--paginate_output" in argv, "marker_pages.py split needs page markers"
    assert "--page_range" not in argv
    assert proc.stdout.strip().splitlines()[-1] == str(tmp_path / "out" / "my book" / "my book.md")


def test_sample_limits_pages(run):
    proc, record = run("--sample")

    assert proc.returncode == 0, proc.stderr
    assert "--page_range" in record["argv"]


@pytest.fixture
def fake_python(tmp_path):
    py = tmp_path / "py" / "fake-python"
    py.parent.mkdir()
    py.write_text(FAKE_PYTHON.format(python=sys.executable, marker=FAKE_MARKER.format(python=sys.executable)))
    py.chmod(0o755)
    return str(py)


def test_install_creates_venv_that_later_runs_use(run, tmp_path, fake_python):
    proc, _ = run("--install", marker_on_path=False, MARKER_PYTHON=fake_python)

    venv_marker = tmp_path / "venv" / "bin" / "marker_single"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == str(venv_marker)
    assert venv_marker.exists()

    proc, record = run(marker_on_path=False)
    assert proc.returncode == 0, proc.stderr
    assert record is not None, "conversion did not use the venv's marker_single"


def test_install_refuses_python_older_than_3_10(run, tmp_path, fake_python):
    proc, _ = run("--install", marker_on_path=False, MARKER_PYTHON=fake_python, FAKE_PYTHON_TOO_OLD="1")

    assert proc.returncode == 4
    assert not (tmp_path / "venv").exists()


def test_missing_marker_exits_2_and_points_at_install(run):
    proc, record = run(marker_on_path=False)

    assert proc.returncode == 2
    assert "--install" in proc.stderr
    assert record is None
