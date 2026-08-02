import pytest

from p2c.assemble import (
    AssembleError,
    FrontMatter,
    assemble,
    module_filename,
    parse_front_matter,
    render_front_matter,
)

OUTLINE = {
    "title": "Operating Systems",
    "subject_domain": "systems",
    "source_decks": ["week1.pdf", "week2.pdf"],
    "modules": [
        {
            "id": "m-memory",
            "title": "Virtual Memory",
            "prerequisites": ["Binary arithmetic", "Pointers"],
            "topics": [{"id": "tlb", "title": "The TLB", "slide_refs": [], "jargon": [],
                        "diagrams": [], "gaps": []}],
        },
        {
            "id": "m-sched",
            "title": "Scheduling",
            "prerequisites": [],
            "topics": [{"id": "rr", "title": "Round robin", "slide_refs": [], "jargon": [],
                        "diagrams": [], "gaps": []}],
        },
    ],
}


def write_modules(tmp_path, bodies=("<!-- topic: tlb -->\n### The TLB\n\nBody one.",
                                    "<!-- topic: rr -->\n### Round robin\n\nBody two.")):
    modules = tmp_path / "modules"
    modules.mkdir()
    (modules / "01-virtual-memory.md").write_text(bodies[0])
    (modules / "02-scheduling.md").write_text(bodies[1])
    return modules


def test_module_filename_is_index_and_slug():
    assert module_filename(1, OUTLINE["modules"][0]) == "01-virtual-memory.md"
    assert module_filename(2, OUTLINE["modules"][1]) == "02-scheduling.md"
    assert module_filename(10, {"title": "I/O & Devices"}) == "10-i-o-devices.md"


def test_front_matter_round_trips():
    fm = FrontMatter(
        title="Operating Systems: a survey",
        subject_domain="systems",
        theme="slate",
        source_decks=["week1.pdf", "week2.pdf"],
    )
    text = render_front_matter(fm) + "\n# Body\n"
    parsed, body = parse_front_matter(text)
    assert parsed == fm
    assert body.strip() == "# Body"


def test_front_matter_renders_a_block_list():
    text = render_front_matter(
        FrontMatter("T", "theory", "parchment", ["a.pdf", "b.pdf"])
    )
    assert text.startswith("---\n")
    assert "title: T\n" in text
    assert "subject_domain: theory\n" in text
    assert "theme: parchment\n" in text
    assert "source_decks:\n  - a.pdf\n  - b.pdf\n" in text
    assert text.rstrip().endswith("---")


def test_front_matter_handles_no_source_decks():
    parsed, _ = parse_front_matter(render_front_matter(FrontMatter("T", "other", "slate", [])))
    assert parsed.source_decks == []


@pytest.mark.parametrize(
    "text,message",
    [
        ("# no front matter\n", "must start with a '---' front matter block"),
        ("---\ntitle: T\n", "front matter block is not closed"),
        ("---\ntitle: T\ntheme: slate\n---\n", "missing front matter key 'subject_domain'"),
        ("---\ntitle: T\nsubject_domain: systems\ntheme: slate\nbogus\n---\n",
         "unparseable front matter line"),
    ],
)
def test_parse_front_matter_rejects_bad_input(text, message):
    with pytest.raises(AssembleError, match=message):
        parse_front_matter(text)


def test_render_front_matter_rejects_a_multiline_value():
    with pytest.raises(AssembleError, match="may not contain a newline"):
        render_front_matter(FrontMatter("two\nlines", "systems", "slate", []))


def test_assemble_produces_front_matter_h1_and_modules_in_order(tmp_path):
    modules = write_modules(tmp_path)
    course = assemble(OUTLINE, modules)
    fm, body = parse_front_matter(course)
    assert fm.title == "Operating Systems"
    assert fm.theme == "slate"
    assert fm.source_decks == ["week1.pdf", "week2.pdf"]
    assert body.lstrip().startswith("# Operating Systems")
    assert body.index("## Virtual Memory") < body.index("## Scheduling")
    assert "Body one." in body and "Body two." in body
    assert course.endswith("\n")


def test_assemble_emits_a_prereq_block_only_when_there_are_prerequisites(tmp_path):
    course = assemble(OUTLINE, write_modules(tmp_path))
    assert "```prereq\n- Binary arithmetic\n- Pointers\n```" in course
    scheduling = course[course.index("## Scheduling") :]
    assert "```prereq" not in scheduling


def test_assemble_preserves_module_bodies_verbatim(tmp_path):
    body = "<!-- topic: tlb -->\n### The TLB\n\n```quiz\nq: x\n- [x] y\n- [ ] z\n- [ ] w\nwhy: y\n```"
    modules = write_modules(tmp_path, bodies=(body, "<!-- topic: rr -->\n### Round robin\n\nB."))
    assert body in assemble(OUTLINE, modules)


def test_assemble_reports_the_expected_path_of_a_missing_module(tmp_path):
    modules = write_modules(tmp_path)
    (modules / "02-scheduling.md").unlink()
    with pytest.raises(AssembleError, match="02-scheduling.md"):
        assemble(OUTLINE, modules)


def test_assemble_reports_an_empty_module_file(tmp_path):
    modules = write_modules(tmp_path)
    (modules / "01-virtual-memory.md").write_text("   \n")
    with pytest.raises(AssembleError, match="01-virtual-memory.md is empty"):
        assemble(OUTLINE, modules)


def test_collect_sources_reads_every_topic_research_file(tmp_path):
    from p2c.assemble import collect_sources
    from p2c.sources import Source

    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "tlb.md").write_text("## Sources\n- A: https://a.example\n")
    (research_dir / "sched.md").write_text("## Sources\n- B: https://b.example\n")

    outline = {
        "modules": [
            {"topics": [{"id": "tlb"}, {"id": "sched"}]},
        ]
    }
    result = collect_sources(research_dir, outline)
    assert result == {
        "tlb": [Source("A", "https://a.example")],
        "sched": [Source("B", "https://b.example")],
    }


def test_collect_sources_tolerates_a_missing_research_file(tmp_path):
    from p2c.assemble import collect_sources

    research_dir = tmp_path / "research"
    research_dir.mkdir()
    outline = {"modules": [{"topics": [{"id": "tlb"}]}]}
    assert collect_sources(research_dir, outline) == {"tlb": []}


def test_collect_sources_tolerates_a_missing_research_directory(tmp_path):
    from p2c.assemble import collect_sources

    outline = {"modules": [{"topics": [{"id": "tlb"}]}]}
    assert collect_sources(tmp_path / "does-not-exist", outline) == {"tlb": []}
