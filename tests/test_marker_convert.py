"""scripts/marker_convert.sh picks marker's LLM service from the API key and
keeps the key out of marker's argv. A fake `marker_single` on PATH records
what it was called with.
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
config = Path(args[args.index("--config_json") + 1]).read_text()
out = Path(args[args.index("--output_dir") + 1])
stem = Path(args[0]).stem
(out / stem).mkdir(parents=True)
(out / stem / (stem + ".md")).write_text("# Converted\\n")
Path(os.environ["FAKE_MARKER_LOG"]).write_text(json.dumps({{"argv": args, "config": json.loads(config)}}))
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

    def _run(*flags, **keys):
        env = {
            "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "TMPDIR": str(tmp_path),
            "FAKE_MARKER_LOG": str(log),
            **keys,
        }
        proc = subprocess.run(
            ["bash", str(SCRIPT), *flags, str(pdf), str(tmp_path / "out")],
            env=env,
            capture_output=True,
            text=True,
            start_new_session=True,  # no controlling terminal, so no prompt
        )
        record = json.loads(log.read_text()) if log.exists() else None
        return proc, record

    return _run


def test_claude_key_selects_claude_service(run, tmp_path):
    key = "sk-ant-api03-secret"
    proc, record = run(ANTHROPIC_API_KEY=key)

    assert proc.returncode == 0, proc.stderr
    argv = record["argv"]
    assert argv[argv.index("--llm_service") + 1] == "marker.services.claude.ClaudeService"
    assert record["config"] == {"claude_api_key": key, "claude_model_name": "claude-sonnet-5-5"}
    assert key not in " ".join(argv)
    assert "--page_range" not in argv
    assert proc.stdout.strip().splitlines()[-1] == str(tmp_path / "out" / "my book" / "my book.md")
    assert not list(tmp_path.glob("marker-config.*")), "config with the key was left behind"


def test_openai_key_selects_openai_service_and_sample_limits_pages(run):
    key = "sk-proj-secret"
    proc, record = run("--sample", OPENAI_API_KEY=key, MARKER_MODEL="gpt-x")

    assert proc.returncode == 0, proc.stderr
    argv = record["argv"]
    assert argv[argv.index("--llm_service") + 1] == "marker.services.openai.OpenAIService"
    assert record["config"] == {"openai_api_key": key, "openai_model": "gpt-x"}
    assert key not in " ".join(argv)
    assert "--page_range" in argv


@pytest.mark.parametrize(
    "keys",
    [
        {},  # no key and no terminal to ask on
        {"OPENAI_API_KEY": "AIza-not-openai"},
    ],
)
def test_missing_or_unrecognized_key_exits_3_without_running_marker(run, keys):
    proc, record = run(**keys)

    assert proc.returncode == 3
    assert record is None
