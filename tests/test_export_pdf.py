import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.make_fixtures import make_pdf
from p2c.exportpdf import (
    ExportError,
    ExportResult,
    export_pdf,
    find_chromium,
    pdf_command,
)

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "course.html"


@pytest.fixture
def html(tmp_path):
    target = tmp_path / "course.html"
    target.write_text(GOLDEN.read_text())
    return target


def fake_chromium(tmp_path, *, pages=2, exit_code=0):
    """A stand-in browser: writes a real PDF to --print-to-pdf, or fails."""
    script = tmp_path / "fake-chromium"
    body = "import sys, pathlib\n"
    if exit_code:
        body += f"sys.stderr.write('boom\\n')\nsys.exit({exit_code})\n"
    else:
        data = make_pdf([["page"]] * pages)
        body += (
            "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--print-to-pdf=')][0]\n"
            f"pathlib.Path(out).write_bytes({data!r})\n"
        )
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return str(script)


def test_find_chromium_prefers_an_explicit_path(tmp_path):
    fake = fake_chromium(tmp_path)
    assert find_chromium(fake) == fake


def test_find_chromium_honours_the_env_var(tmp_path, monkeypatch):
    fake = fake_chromium(tmp_path)
    monkeypatch.setenv("P2C_CHROMIUM", fake)
    assert find_chromium() == fake


def test_find_chromium_returns_none_when_nothing_is_installed(monkeypatch):
    monkeypatch.delenv("P2C_CHROMIUM", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert find_chromium() is None


def test_pdf_command_has_the_flags_the_diagrams_need(tmp_path):
    cmd = pdf_command("chromium", tmp_path / "c.html", tmp_path / "c.pdf", tmp_path / "profile")
    joined = " ".join(cmd)
    assert cmd[0] == "chromium"
    assert "--headless=new" in cmd
    assert "--virtual-time-budget=20000" in cmd
    assert "--run-all-compositor-stages-before-draw" in cmd
    assert f"--print-to-pdf={tmp_path / 'c.pdf'}" in cmd
    assert "--no-pdf-header-footer" in cmd
    assert f"--user-data-dir={tmp_path / 'profile'}" in cmd
    assert joined.endswith((tmp_path / "c.html").as_uri())


def test_export_skips_when_no_browser_is_available(html, tmp_path, monkeypatch):
    monkeypatch.delenv("P2C_CHROMIUM", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr("p2c.exportpdf.find_chromium", lambda explicit=None: None)
    result = export_pdf(html, tmp_path / "course.pdf")
    assert isinstance(result, ExportResult)
    assert result.skipped is True
    assert result.pdf is None
    assert "Download PDF" in result.reason
    assert not (tmp_path / "course.pdf").exists()


def test_export_writes_a_pdf_and_counts_pages(html, tmp_path):
    result = export_pdf(html, tmp_path / "course.pdf", chromium=fake_chromium(tmp_path, pages=3))
    assert result.skipped is False
    assert result.pdf == tmp_path / "course.pdf"
    assert result.pages == 3
    assert result.pdf.read_bytes().startswith(b"%PDF-")


def test_export_raises_when_the_browser_fails(html, tmp_path):
    with pytest.raises(ExportError, match="exited 1"):
        export_pdf(html, tmp_path / "course.pdf", chromium=fake_chromium(tmp_path, exit_code=1))


def test_export_raises_when_no_pdf_appears(html, tmp_path):
    silent = tmp_path / "silent"
    silent.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n")
    silent.chmod(0o755)
    with pytest.raises(ExportError, match="wrote no PDF"):
        export_pdf(html, tmp_path / "course.pdf", chromium=str(silent))


def test_export_rejects_a_missing_html_file(tmp_path):
    with pytest.raises(ExportError, match="no such file"):
        export_pdf(tmp_path / "nope.html", tmp_path / "course.pdf", chromium="chromium")


def _run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "export-pdf"), *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_exit_0_and_json_summary(html, tmp_path):
    proc = _run_cli(
        "--html", html, "--out", tmp_path / "course.pdf",
        "--chromium", fake_chromium(tmp_path, pages=2),
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary == {
        "pdf": str(tmp_path / "course.pdf"),
        "pages": 2,
        "skipped": False,
        "reason": None,
    }


def test_cli_exit_6_and_a_skip_note_when_chromium_is_absent(html, tmp_path):
    proc = _run_cli(
        "--html", html, "--out", tmp_path / "course.pdf",
        "--chromium", "definitely-not-a-browser",
    )
    assert proc.returncode == 6
    assert json.loads(proc.stdout)["skipped"] is True
    assert proc.stderr.startswith("SKIP:")
    assert "Download PDF" in proc.stderr


def test_cli_exit_2_without_arguments():
    assert _run_cli().returncode == 2


@pytest.mark.skipif(
    all(shutil.which(name) is None for name in
        ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")),
    reason="no Chromium installed",
)
def test_real_chromium_produces_a_pdf(html, tmp_path):
    result = export_pdf(html, tmp_path / "course.pdf")
    assert result.skipped is False
    assert result.pages > 0
