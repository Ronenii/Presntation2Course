# SDD ledger — plan: docs/superpowers/plans/2026-07-28-presentation2course.md
Worktree: /home/roneng/Presntation2Course/.claude/worktrees/p2c-implementation
Branch: worktree-p2c-implementation (base 1cf6033)

Task 1: complete (commits 1cf6033..6b80247, review clean)
Task 2: minor (deferred): make_pdf is Latin-1-only and undocumented as such (make_fixtures.py:79,96,102); no empty-pages guard; make_pdf lacks a determinism test like make_pptx has
Task 2: complete (commits 6b80247..a905a34, review clean)
Task 3: fix round 1/5 (2 addressed, 0 open; commits 00f96ec..b0f15e2)
Task 3: minor (deferred): /Count fallback window (normalize.py:79-86) is order/position-dependent within 500 bytes of the /Type token; only reachable when zero literal /Type /Page leaves exist (compressed object streams), could false-reject a legitimate deck
Task 3: complete (commits a905a34..b0f15e2, 1 minor deferred)
Task 4: parked — extract_fences only matches exactly 3-backtick fences (no CommonMark-style 4-vs-3 nesting), so a fenced code sample cannot be embedded inside a quiz/glossary/analogy block — ruling: real limitation, inherited from the plan's own reference code, accepted because every block kind this pipeline defines (quiz, glossary, mermaid, analogy, prereq, unverified) is grammar-restricted to plain text or short prose; none legitimately needs an embedded fenced code block. Revisit only if a later task's content format needs to embed one.
Task 4: minor (deferred): _INLINE_CODE regex doesn't handle double-backtick spans or escaped backticks (blocks.py:29); no test for extract_fences with an uppercase fence kind (e.g. ```QUIZ)
Task 4: complete (commits b0f15e2..986a267, 1 parked, 2 minor deferred)
Task 5: minor (deferred): no test for duplicate why: lines (quiz.py:159-160); no test for multi-line q: wrapping (quiz.py:163-165); report line-count claims did not match diff stat (cosmetic)
Task 5: fix round 1/5 re-reviewed (addressed, no new breakage; commits bf90a99..f17d9be)
Task 5: complete (commits 986a267..f17d9be, 3 minor deferred)
Task 6: minor (deferred): [^:]+ -> [^:]* regex fix in glossary.py:31 has no inline comment explaining why; unused `line` var in enumerate loop (glossary.py:206); no test for a term containing regex metacharacters (e.g. "C++")
Task 6: complete (commits 316d380..ac04d3a, review clean)
Task 7: NOT STARTED — brief generated (task-7-brief.md), implementer dispatch was rejected by the user before any subagent work began. A stray, non-collecting tests/test_outline.py (matches the brief's Step 1 RED test verbatim, imports p2c.outline which does not exist) is sitting untracked in the worktree — origin unclear (possibly a partial artifact from the rejected dispatch), NOT committed, breaks a bare `pytest` collection run. Resume: either delete this stray file and re-dispatch Task 7 from the brief, or use it as the starting RED state if it matches the brief exactly (verify first — do not trust it without comparing to task-7-brief.md Step 1).
