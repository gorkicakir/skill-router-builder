# Test results

## Unit tests

`python -m unittest discover -s tests -v` runs 25 tests on small synthetic skill sets (no network, no real skills needed). They cover:

| Area | What is checked |
|---|---|
| Discovery | all skills found, nested copies ignored, duplicate names reported, folded YAML descriptions parsed |
| Grouping | related skills form routers, unrelated skills are never forced together, file-linked skills stay together, `standalone` respected, works without `networkx` |
| Output | valid name/description in every SKILL.md, every member listed and bundled, ZIP layout, config anchors and extra triggers, long descriptions trimmed, description overrides, token report |
| Updates | a new skill joins the right router without reshuffling others, unrelated additions leave other routers untouched, config pins override the previous layout, only changed outputs are flagged for re-upload, removed skills are reported |
| Upload limits | exactly one SKILL.md per bundle, oversized routers split under the file limit, unsplittable bundles fail with advice, dev-only and excluded files left out |

Bugs found by these tests and fixed are listed with their causes in [CHANGELOG.md](../CHANGELOG.md).

## Benchmark on a real collection

A collection of 78 public skills: a marketing pack, an agent-systems pack, a design pack and a few single skills.

**Context cost**

| | Before (78 skills) | After (6 skills) |
|---|---|---|
| Skill text loaded in every conversation | ~14,700 tokens | ~1,200 tokens (-92%) |
| Conversation that uses a marketing router | ~14,700 | ~3,800 |
| Conversation that uses the agent-systems router | ~14,700 | ~3,000 |

Token counts are estimated from character counts. The host's own plugin report gave ~13,300 always-on tokens for the same packs before routing, so the estimate is in the right range.

**Routing accuracy**

70 requests in two languages across marketing, design and agent-system tasks, plus requests that should not trigger any skill. The same model picked a skill from the flat list of 78 and, separately, from the routers (top level first, then the router map). Two router layouts were tested: one marketing router of 52 skills, and the upload-ready layout where the 200-file limit splits marketing in two.

| | Flat list | 5 routers | 6 routers (upload-ready) |
|---|---|---|---|
| Correct skill | 69 / 70 | 70 / 70 | 69 / 70 |
| Skill triggered when none should | 0 | 0 | 0 |

Each layout missed at most one request, and each miss was a near-neighbour skill, so accuracy is effectively unchanged while the always-loaded text drops by more than 90%.

**Generality**

| Scenario | Result |
|---|---|
| 3 new skills added to an existing build | existing layout unchanged; the related one joined the matching router, unrelated ones stayed standalone |
| A different collection of 19 unrelated skills | nothing grouped (correct: no shared topic) |
| Both collections together (97 skills) | 24 top-level skills, -79% always-loaded text |

## Benchmark 2: two large public collections

To check that the first benchmark was not a property of one collection, the tool was run unchanged (v1.2.0, default settings, `networkx` installed) on two popular public skill collections. Both are MIT licensed; thank you to their authors for publishing them.

| Collection | Skills | Source |
|---|---|---|
| Scientific skills by K-Dense-AI | 177 (`skills/`) | [K-Dense-AI/claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills) |
| Business and engineering skills by Alireza Rezvani | 380 unique (every `*/skills/*` folder, 19 duplicate names skipped) | [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) |

Snapshot: 2026-10-31. Token counts below are real counts (`tiktoken`, `cl100k_base`) of the skill listing an agent sees in every conversation: one `- name: description` line per top-level skill. The first benchmark used a character-based estimate; this one does not.

**Context cost**

| Collection | Top-level skills | Listing, before | Listing, after | Change |
|---|---|---|---|---|
| Author's own collection (Benchmark 1, estimated) | 78 → 6 | ~14,700 | ~1,200 | -92% |
| K-Dense-AI scientific (177) | 177 → 112 | 14,867 tokens | 9,573 tokens | **-36%** |
| alirezarezvani (380) | 380 → 36 | 19,566 tokens | 4,612 tokens | **-76%** |

The scientific collection groups less: 102 of its 177 skills are single-purpose wrappers around one library (`astropy`, `pydicom`, `cantera`, ...) with little in common, and the tool keeps unrelated skills standalone by design rather than forcing them into a router. Lowering `min_affinity` to 1.0 with `resolution` 0.5 gives 177 → 84 (-48%); the default run is reported above.

**Routing accuracy**

For each collection, 35 requests were written in plain user language: 32 that target one specific skill (a mix of skills inside routers and standalone skills: 16 + 16 for the scientific collection, 26 + 6 for the business one) and 3 general questions that should trigger no skill. The same model picked a skill from the flat list and, separately, from the router layout (top level first, then the chosen router's map). The picker was never shown the expected answer.

| Collection | Flat list | Routers | Triggered when none should |
|---|---|---|---|
| K-Dense-AI scientific (177) | 35 / 35 | 35 / 35 | 0 / 0 |
| alirezarezvani (380) | 35 / 35 | 35 / 35 | 0 / 0 |

Request sets: `tests/benchmark2/`.

**Notes from the runs**

- The 380-skill collection failed validation on the first run: one skill (`skill-tester`) ships an example `assets/sample-skill/SKILL.md`, so its bundle contained two `SKILL.md` files. `--exclude "assets/sample-skill/*"` fixes it; handling nested example skills automatically is on the list.
- Without `networkx`, the fallback clustering grouped less on the scientific collection (177 → 124, -31%). Install `networkx` for the numbers above.

**Why this matters for Claude Code specifically**

Claude Code caps the skill listing at 1% of the model's context window and, when the listing overflows, silently drops the descriptions of the least-used skills (names stay, matching keywords go). A 380-skill listing of ~19,600 tokens is far over that budget; the 36-entry router listing is much closer to it, so far fewer descriptions are lost. Outside Claude Code (API, claude.ai, other agents) there is no such cap and the saving is simply the token difference above.
