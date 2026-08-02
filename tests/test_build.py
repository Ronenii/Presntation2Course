import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from p2c.build import build, main
from p2c.imagery import ImageryError
from p2c.theme import TEMPLATE_PLACEHOLDERS

REPO = Path(__file__).resolve().parents[1]
MINI = REPO / "tests" / "fixtures" / "mini-course"
ASSETS = REPO / "assets"
GOLDEN = REPO / "tests" / "golden" / "course.html"
MINI_HE = REPO / "tests" / "fixtures" / "mini-course-he"
GOLDEN_HE = REPO / "tests" / "golden" / "course-he.html"


def _seed_research(out_dir, entries):
    """Writes '## Sources' notes files under .p2c/research/ per Task 10's grammar
    ('- Title: url'), so builds exercise a real, non-empty Sources appendix."""
    research = out_dir / ".p2c" / "research"
    research.mkdir(parents=True)
    for topic_id, lines in entries.items():
        body = "## Sources\n" + "".join(f"- {line}\n" for line in lines)
        (research / f"{topic_id}.md").write_text(body)


@pytest.fixture
def built(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    _seed_research(tmp_path, {
        "tlb": ["Intel 64 and IA-32 Architectures SDM: https://example.com/intel-sdm"],
        "round-robin": ["Operating Systems: Three Easy Pieces: https://example.com/ostep"],
    })
    return build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS)


@pytest.fixture
def built_he(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    _seed_research(tmp_path, {
        "tlb": ["Intel 64 and IA-32 Architectures SDM: https://example.com/intel-sdm"],
    })
    return build(MINI_HE / "outline.json", MINI_HE / "modules", tmp_path, ASSETS)


def test_build_writes_all_three_artifacts(built, tmp_path):
    assert built.course_md == tmp_path / "operating-systems-foundations.md"
    assert built.course_html == tmp_path / "operating-systems-foundations.html"
    assert built.findings_path == tmp_path / ".p2c" / "review" / "build-findings.json"
    for path in (built.course_md, built.course_html, built.findings_path):
        assert path.is_file()


def test_the_mini_course_builds_clean(built):
    assert [f.code for f in built.findings] == []
    assert json.loads(built.findings_path.read_text()) == []


def test_theme_comes_from_subject_domain(built):
    assert built.theme == "slate"
    html = built.course_html.read_text()
    assert 'data-course-theme="slate"' in html
    assert "--mermaid-primary: #e4ebf7;" in html


def test_theme_can_be_overridden(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS, theme="parchment")
    assert result.theme == "parchment"
    assert "ui-serif" in result.course_html.read_text()


def test_no_placeholder_survives_in_the_html(built):
    html = built.course_html.read_text()
    for placeholder in TEMPLATE_PLACEHOLDERS:
        assert placeholder not in html


def test_the_html_is_self_contained(built):
    """No script/style/image/etc. asset is fetched from the network. Citation
    links in the Sources appendix are a sanctioned exception -- they are plain
    <a href> anchors, never a resource-loading tag, and clicking one is the
    reader's own choice rather than the page reaching out on load (this is also
    exactly what validate.py's own _external_requests scan permits).

    This only covers the resource-tag-substring case; the fuller external-request
    vector coverage (CSS url(), fetch(), XMLHttpRequest, etc.) lives in
    tests/test_validate.py."""
    html = built.course_html.read_text()
    assert "<style>" in html
    assert "@import" not in html
    for tag in ("script", "img", "link", "iframe", "video", "audio", "source",
                "embed", "object", "track"):
        assert not re.search(
            rf'<{tag}\b[^>]*\b(?:src|href|data)\s*=\s*["\']https?://', html, re.IGNORECASE
        ), tag
    assert 'href="https://example.com/intel-sdm"' in html  # the sanctioned exception itself


def test_mermaid_is_not_inlined_when_the_course_has_no_diagrams(built):
    html = built.course_html.read_text()
    assert "__esbuild_esm_mermaid_nm" not in html
    assert len(html) < 200_000


def test_anime_is_not_inlined_when_the_course_has_no_animate_blocks(tmp_path):
    # The `built` fixture's mini-course fixture already carries `animate` blocks
    # (added by earlier visual-enhancement work), so it can't stand in for "no
    # animate blocks in the course" here. Strip them out of a fresh copy instead.
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        text = (MINI / "modules" / name).read_text()
        text = re.sub(r"```animate\n.*?```\n", "", text, flags=re.DOTALL)
        modules.joinpath(name).write_text(text)
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    assert result.rendered.uses_animate is False
    html = result.course_html.read_text()
    assert "Julian Garnier" not in html


def test_anime_is_inlined_once_when_an_animate_block_is_present(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write(
            "\n```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    # The vendored anime.min.js license banner mentions the author twice
    # (@author and @copyright lines), so "Julian Garnier" naturally appears
    # twice per inclusion. What "inlined once" means is that the vendored
    # bundle's full text is embedded exactly one time, not per-occurrence.
    vendored_anime_js = (ASSETS / "vendor" / "anime.min.js").read_text()
    assert "Julian Garnier" in html
    assert html.count(vendored_anime_js) == 1
    assert [f.code for f in result.findings] == []


def test_mermaid_is_inlined_once_when_a_diagram_is_present(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write("\n```mermaid\nflowchart LR\n  A[Run] --> B[Queue]\n```\n")
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    assert html.count("__esbuild_esm_mermaid_nm") >= 1
    assert html.count('<div class="mermaid" dir="ltr">') == 1
    assert [f.code for f in result.findings] == []


def test_course_md_is_the_source_of_truth_and_reproducible(built, tmp_path):
    first = built.course_md.read_text()
    second = tmp_path / "second"
    normalized = second / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    _seed_research(second, {
        "tlb": ["Intel 64 and IA-32 Architectures SDM: https://example.com/intel-sdm"],
        "round-robin": ["Operating Systems: Three Easy Pieces: https://example.com/ostep"],
    })
    again = build(MINI / "outline.json", MINI / "modules", second, ASSETS)
    assert again.course_md.read_text() == first
    assert again.course_html.read_text() == built.course_html.read_text()


def test_the_shipped_html_declares_language_and_direction(built):
    # Anchored on the <html> tag's own attributes specifically, not a bare substring
    # search — a mermaid container also emits dir="ltr" (Task 4), so a loose
    # 'dir="ltr"' in html check would pass even if the <html> tag's own dir were wrong,
    # as long as some diagram happened to be present elsewhere in the page.
    html = built.course_html.read_text()
    assert html.startswith('<!doctype html>\n<html lang="en" dir="ltr"')


def test_an_rtl_language_gets_dir_rtl_and_its_own_lang(tmp_path):
    outline = json.loads((MINI / "outline.json").read_text())
    outline["language"] = {"name": "Hebrew", "code": "he"}
    outline_path = tmp_path / "outline.json"
    outline_path.write_text(json.dumps(outline))
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(outline_path, MINI / "modules", out, ASSETS)
    html = result.course_html.read_text()
    assert 'lang="he"' in html
    assert 'dir="rtl"' in html


def test_content_reaches_the_html_with_structure(built):
    html = built.course_html.read_text()
    assert "<h1 id=\"operating-systems-foundations\">" in html
    assert '<h2 id="virtual-memory">' in html
    assert '<h3 id="what-a-tlb-caches">' in html
    assert 'class="callout callout--analogy"' in html
    assert 'class="callout callout--prereq"' in html
    assert html.count('<details class="quiz"') == 3
    assert '<dt id="def-tlb">TLB</dt>' in html
    assert 'aria-controls="def-tlb"' in html
    assert '<a href="#thrashing">' in html


def test_blocking_findings_are_reported_and_still_render(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    modules.joinpath("01-virtual-memory.md").write_text(
        "<!-- topic: tlb -->\n### What a TLB caches\n\nNo quiz, no glossary.\n"
    )
    modules.joinpath("02-scheduling.md").write_text(
        (MINI / "modules" / "02-scheduling.md").read_text()
    )
    result = build(MINI / "outline.json", modules, tmp_path / "out", ASSETS)
    codes = {f.code for f in result.findings}
    assert "topic_without_quiz" in codes
    assert "topic_missing" in codes
    assert "jargon_without_glossary" in codes
    assert result.course_html.is_file()  # a defective course still renders for review
    recorded = json.loads(result.findings_path.read_text())
    assert {f["code"] for f in recorded} == codes
    assert {f["route"] for f in recorded} <= {"writer", "researcher", "summarizer", "build"}


def test_build_writes_a_sources_section(built):
    course_html = built.course_html.read_text()
    assert '<section class="appendix">' in course_html
    assert '<h2 id="sources">Sources</h2>' in course_html
    assert 'href="https://example.com/intel-sdm"' in course_html


def test_build_falls_back_to_no_sources_message_when_none_are_seeded(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS)
    course_html = result.course_html.read_text()
    assert '<h2 id="sources">Sources</h2>' in course_html
    assert "No external sources were cited." in course_html


def test_matches_the_golden_snapshot(built):
    if os.environ.get("P2C_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(built.course_html.read_text())
    assert built.course_html.read_text() == GOLDEN.read_text(), (
        "course.html changed; re-run with P2C_UPDATE_GOLDEN=1 and review the diff"
    )


def test_the_hebrew_course_builds_clean(built_he):
    assert [f.code for f in built_he.findings] == []


def test_the_hebrew_course_gets_rtl_layout_and_ltr_diagrams(built_he):
    html = built_he.course_html.read_text()
    assert 'lang="he"' in html
    assert 'dir="rtl"' in html
    assert '<div class="mermaid" dir="ltr">' in html
    assert "TLB" in html  # jargon stays in its original form even in a Hebrew course
    assert "<dt id=\"def-tlb\">TLB</dt>" in html


def test_the_hebrew_course_matches_its_golden_snapshot(built_he):
    if os.environ.get("P2C_UPDATE_GOLDEN") == "1":
        GOLDEN_HE.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_HE.write_text(built_he.course_html.read_text())
    assert built_he.course_html.read_text() == GOLDEN_HE.read_text(), (
        "course-he.html changed; re-run with P2C_UPDATE_GOLDEN=1 and review the diff"
    )


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build"), *map(str, args)],
        capture_output=True,
        text=True,
    )


def test_cli_exit_0_and_json_summary(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    proc = _run_cli(
        "--outline", MINI / "outline.json",
        "--modules", MINI / "modules",
        "--out", tmp_path,
        "--assets", ASSETS,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["theme"] == "slate"
    assert summary["quiz_count"] == 3
    assert summary["topics"] == 4
    assert summary["blocking"] == []
    assert summary["uses_mermaid"] is False
    assert summary["course_html"].endswith("operating-systems-foundations.html")


def test_cli_exit_3_on_blocking_findings(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    modules.joinpath("01-virtual-memory.md").write_text("<!-- topic: tlb -->\n### T\n\nBare.\n")
    modules.joinpath("02-scheduling.md").write_text(
        (MINI / "modules" / "02-scheduling.md").read_text()
    )
    proc = _run_cli(
        "--outline", MINI / "outline.json", "--modules", modules,
        "--out", tmp_path / "out", "--assets", ASSETS,
    )
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["blocking"]


def test_cli_exit_1_on_a_missing_module_file(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    proc = _run_cli(
        "--outline", MINI / "outline.json", "--modules", modules,
        "--out", tmp_path / "out", "--assets", ASSETS,
    )
    assert proc.returncode == 1
    assert "01-virtual-memory.md" in proc.stderr


def test_cli_exit_2_without_arguments():
    assert _run_cli().returncode == 2


def test_a_figure_block_resolves_to_an_embedded_base64_image(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("01-virtual-memory.md").open("a") as handle:
        handle.write(
            "\n```figure\nsource: terse.pdf#1\ncaption: The original slide.\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    assert "data-p2c-image-pending" not in html
    assert 'src="data:image/png;base64,' in html
    assert [f.code for f in result.findings] == []


def test_an_unresolvable_figure_source_fails_the_build_naming_topic_and_source(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    # Inserted before the "thrashing" topic marker (rather than appended at EOF) so the
    # figure block still falls under the "tlb" topic section -- the assertion below
    # names that topic specifically.
    virtual_memory = modules.joinpath("01-virtual-memory.md")
    original = virtual_memory.read_text()
    figure_block = (
        "\n```figure\nsource: terse.pdf#99\ncaption: Out of range.\n```\n\n"
    )
    assert "<!-- topic: thrashing -->" in original
    virtual_memory.write_text(
        original.replace("<!-- topic: thrashing -->", figure_block + "<!-- topic: thrashing -->")
    )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    with pytest.raises(ImageryError, match=r"topic 'tlb'.*terse\.pdf#99"):
        build(MINI / "outline.json", modules, out, ASSETS)


def test_resolve_figures_raises_if_a_pending_placeholder_survives_the_regex(tmp_path):
    from p2c.build import _resolve_figures

    # Same content as a real pending figure placeholder, but with the two data-
    # attributes swapped -- _FIGURE_PENDING is a literal-string regex coupled to
    # mdrender._figure_html's exact markup, so this simulates the two drifting out of
    # sync. re.sub matches nothing, and the placeholder must never ship silently.
    drifted = (
        '<figure class="figure" data-p2c-topic="tlb" '
        'data-p2c-image-pending="terse.pdf#1"><img alt="caption"></figure>'
    )
    with pytest.raises(ImageryError, match="figure placeholder was left unresolved"):
        _resolve_figures(drifted, tmp_path)


def test_animate_blocks_render_inside_a_built_course(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write(
            "\n```animate\npattern: state-toggle\nbefore: Ready\nafter: Running\n```\n"
        )
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    result = build(MINI / "outline.json", modules, out, ASSETS)
    html = result.course_html.read_text()
    assert (
        '<div class="anim__state anim__state--before">'
        '<span class="anim__state-label">Before</span>Ready</div>'
    ) in html
    assert [f.code for f in result.findings] == []
