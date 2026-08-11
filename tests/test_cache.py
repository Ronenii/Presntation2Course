import json
import subprocess
import sys
from pathlib import Path

import pytest

from p2c.cache import cache_check, cache_store, hash_normalized_dir

CACHE_PY = Path(__file__).resolve().parents[1] / "scripts" / "cache"


def _write_pdfs(tmp_path, names_and_bytes):
    d = tmp_path / "normalized"
    d.mkdir(parents=True)
    for name, data in names_and_bytes:
        (d / name).write_bytes(data)
    return d


def test_hash_is_stable_for_the_same_bytes_in_the_same_order(tmp_path):
    d = _write_pdfs(tmp_path, [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
    h1 = hash_normalized_dir(d)
    h2 = hash_normalized_dir(d)
    assert h1 == h2
    assert len(h1) == 64  # hex sha256


def test_hash_differs_for_different_bytes(tmp_path):
    d1 = _write_pdfs(tmp_path / "one", [("a.pdf", b"AAA")])
    d2 = _write_pdfs(tmp_path / "two", [("a.pdf", b"AAB")])
    assert hash_normalized_dir(d1) != hash_normalized_dir(d2)


def test_hash_is_order_independent_of_directory_listing_but_content_stable(tmp_path):
    # Same set of (name, bytes) pairs, sorted by name before concatenation --
    # confirms the hash does not depend on filesystem iteration order.
    d = _write_pdfs(tmp_path, [("b.pdf", b"BBB"), ("a.pdf", b"AAA")])
    expected = hash_normalized_dir(d)
    d2 = _write_pdfs(tmp_path / "reordered", [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
    assert hash_normalized_dir(d2) == expected


def test_check_reports_miss_when_cache_dir_absent(tmp_path):
    result = cache_check(tmp_path / ".p2c" / "cache", "deadbeef")
    assert result == {"hit": False}


def test_store_then_check_reports_hit_with_correct_paths(tmp_path):
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text(json.dumps({"title": "t", "modules": []}))
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "topic-a.md").write_text("---\ntopic_id: topic-a\n---\nbody")

    store_result = cache_store(cache_root, "abc123", outline, research_dir)
    assert store_result == {"stored": True}

    check_result = cache_check(cache_root, "abc123")
    assert check_result["hit"] is True
    assert Path(check_result["outline"]).read_text() == outline.read_text()
    assert (Path(check_result["research_dir"]) / "topic-a.md").exists()


def test_check_reports_miss_on_corrupt_cache_entry_never_raises(tmp_path):
    cache_root = tmp_path / ".p2c" / "cache"
    entry = cache_root / "badhash"
    entry.mkdir(parents=True)
    # outline.json missing entirely -- an incomplete/corrupt entry.
    result = cache_check(cache_root, "badhash")
    assert result == {"hit": False}


def test_store_swallows_write_failure_and_reports_it_without_raising(tmp_path, monkeypatch):
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text("{}")
    research_dir = tmp_path / "research"
    research_dir.mkdir()

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("shutil.copy2", _boom)
    result = cache_store(cache_root, "abc123", outline, research_dir)
    assert result["stored"] is False
    assert "error" in result


def test_cli_check_reports_miss_as_json_exit_0(tmp_path):
    normalized = _write_pdfs(tmp_path, [("a.pdf", b"AAA")])
    cache_root = tmp_path / ".p2c" / "cache"
    proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "check",
         "--normalized", str(normalized), "--cache-root", str(cache_root)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["hit"] is False


def test_cli_store_then_cli_check_round_trips(tmp_path):
    normalized = _write_pdfs(tmp_path, [("a.pdf", b"AAA")])
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text(json.dumps({"title": "t", "modules": []}))
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "topic-a.md").write_text("body")

    store_proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "store",
         "--normalized", str(normalized), "--cache-root", str(cache_root),
         "--outline", str(outline), "--research", str(research_dir)],
        capture_output=True, text=True,
    )
    assert store_proc.returncode == 0
    assert json.loads(store_proc.stdout)["stored"] is True

    check_proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "check",
         "--normalized", str(normalized), "--cache-root", str(cache_root)],
        capture_output=True, text=True,
    )
    assert check_proc.returncode == 0
    payload = json.loads(check_proc.stdout)
    assert payload["hit"] is True
