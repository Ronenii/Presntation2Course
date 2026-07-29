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
Task 5: fix round 1/5 (1 addressed — quiz-format.md why: continuation doc gap; commits bf90a99..f17d9be) — RE-REVIEW NOT YET DISPATCHED, resume here

---
Snapshot taken 2026-07-29 for handoff to a remote/cloud session. The live ledger during
local execution lived at the gitignored path
`.superpowers/sdd/2026-07-28-presentation2course/progress.md` (per
superpowers:subagent-driven-development's workspace convention) and does not travel with
this push. To resume: regenerate that workspace with this skill's
`scripts/sdd-workspace docs/superpowers/plans/2026-07-28-presentation2course.md`, copy
this snapshot back in as `progress.md`, and continue from the last line above — Task 5's
fix (commit f17d9be) needs its scoped re-review dispatched before Task 6 starts.
