# Skill Router Builder

**Turn dozens of AI agent skills into a handful of smart routers.**
Less context used in every conversation, the same accuracy, and updates that do not break your setup.

---

## The problem

Agent skills (folders with a `SKILL.md`) are loaded lazily: the full instructions only load when a skill is used. But the **name and description of every installed skill** is loaded in every conversation so the agent can choose. Install 80 skills and you pay for 80 descriptions every time, around 15,000 tokens, before you have typed anything. Similar skills also start competing with each other.

**Claude Code is a special case.** It caps the skill listing at about 1% of the model's context window (roughly 2,000 tokens on a 200K model) and, when the listing overflows, silently drops the descriptions of the skills you use least: the names stay, the keywords Claude matches on are gone ([docs](https://code.claude.com/docs/en/skills#skill-descriptions-are-cut-short)). So in Claude Code the problem with 80+ skills is not mainly the tokens; it is that most descriptions never reach the model. A router listing is many times shorter (36 entries instead of 380 in the benchmark below), so it fits the budget far better and far fewer descriptions are dropped. On the API, claude.ai and other agents there is no such cap and the saving is the plain token difference.

## The solution

Skill Router Builder groups related skills into **router skills**. A router has one short description at the top level and a map inside that points to its members. The agent first picks the router, reads its map, then opens only the skill it needs.

```
Before                                  After
78 skills in the list                   6 skills in the list
  ab-testing                              marketing-copy   -> map -> 31 skills
  ad-creative                             marketing-seo    -> map -> 21 skills
  ads                                     agent-systems    -> map -> 19 skills
  ... 75 more                             design-tools     -> map ->  5 skills
                                          stop-slop
                                          remotion
~14,700 tokens per conversation         ~1,200 tokens per conversation
```

Nothing is written by hand. The tool reads your skills, finds which ones belong together and writes every map from the skills' own descriptions. Works with any skill collection.

## Results

Measured on the author's own collection and on two large public collections, with the tool unchanged (default settings):

| Collection | Top-level skills | Skill text in every conversation | Picking the right skill |
|---|---|---|---|
| Author's own collection (78 skills: marketing, agent systems, design) | 78 → 6 | ~14,700 → ~1,200 tokens (**-92%**, estimated) | 69 / 70 → 69 / 70 |
| [K-Dense-AI/claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills) (177 skills) | 177 → 112 | 14,867 → 9,573 tokens (**-36%**, counted) | 35 / 35 → 35 / 35 |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) (380 skills) | 380 → 36 | 19,566 → 4,612 tokens (**-76%**, counted) | 35 / 35 → 35 / 35 |

Details, the request sets and the unit tests: [tests/RESULTS.md](tests/RESULTS.md)

### Benchmark 2: two public collections

![Running the tool on a 380-skill collection](tests/benchmark2/benchmark2.gif)

- Collections: the scientific skills by K-Dense-AI (177 skills) and the business and engineering skills by Alireza Rezvani (380 unique skills). Both MIT; thanks to their authors for publishing them.
- Token counts are real (`tiktoken`, `cl100k_base`) over the `name: description` listing an agent sees every conversation, not character estimates.
- The business collection groups well: 380 → 36 top-level entries, 19,566 → 4,612 tokens (-76%).
- The scientific collection groups less: nothing is forced together, and 102 of its 177 skills are single-library wrappers with little in common, so 177 → 112 (-36%). Looser settings (`min_affinity` 1.0, `resolution` 0.5) give 177 → 84 (-48%).
- Routing accuracy: 35 plain-language requests per collection (32 targeting one skill, 3 that should trigger nothing). Flat list 35/35, routers 35/35, no false triggers, in both collections.
- One real-world snag: a skill that ships an example `SKILL.md` inside `assets/` breaks the one-`SKILL.md` rule; `--exclude "assets/sample-skill/*"` fixes it (automatic handling is planned).
- Install `networkx`: without it the fallback clustering grouped less (177 → 124).

## How it groups skills

It builds a web of connections between skills:

1. **File links**: a skill that uses another skill's files (`../other/script.py`). These are always kept together, so nothing breaks.
2. **Mentions**: a skill that says "see the X skill" or names X.
3. **Similarity**: how much the names and descriptions overlap.

Community detection then finds the natural clusters. Big clusters become routers. Small clusters and loosely connected skills stay on their own, so unrelated skills are never forced together. A general-purpose skill (for example a writing-style skill) stays standalone automatically.

Bundles are kept upload-ready: each one holds exactly one `SKILL.md` (bundled sub-skills keep their instructions in `INSTRUCTIONS.md`), development-only files such as `evals/` and `tests/` are left out, and a router that would exceed the file limit (200 by default) is split into smaller routers along the same connection graph.

Each generated router contains:
- a short description (under 1024 characters) listing its members and their main trigger phrases,
- a one-line summary and trigger phrases for every member,
- an "easily confused" list of near-duplicate skills, so the agent picks carefully between them.

## Quick start

Requirements: Python 3.8+. Optional: `networkx` (better clustering), `git` (for GitHub sources).

```bash
git clone https://github.com/<your-account>/skill-router-builder
cd skill-router-builder

# 1. preview the grouping
python scripts/build_routers.py --src ~/path/to/skills --out out --dry-run

# 2. build
python scripts/build_routers.py --src ~/path/to/skills --out out
```

`out/` now contains one folder and one `.zip` per top-level skill, ready to copy into a skills folder or to upload to a host that accepts skill ZIPs.

The report at the end shows how much you saved:

```
Result:
  top-level skills : 78 -> 6
  always-loaded    : ~14731 -> ~1190 tokens per conversation (92% less)
  router map marketing-copy: ~2630 tokens, read only when that area is used
```

## Adding, removing and updating skills

Run the same command again with the same `--out` folder. The previous layout is kept:

- existing skills stay where they are,
- a new skill joins the router it is most connected to, or stays standalone if it is unrelated,
- the report tells you exactly which ZIPs changed and need to be uploaded again.

```
  re-upload needed : ['marketing']
  since last build : +1 ['new-skill'] | -0 [] | changed [] | regrouped []
```

Use `--rebalance` to regroup everything from scratch.

### Skills from GitHub

List your sources once and update them with one command:

```json
{
  "sources": [
    {"repo": "coreyhaines31/marketingskills", "paths": ["skills/*"]},
    {"repo": "hardikpandya/stop-slop", "paths": ["."], "as": "stop-slop"}
  ],
  "local": ["~/my-skills"]
}
```

```bash
python scripts/sync_sources.py --sources sources.json --work work
python scripts/build_routers.py --src work/skills --out work/out
```

`sync_sources.py` clones or pulls every repository and tells you which ones changed upstream.

## Configuration (optional)

Everything works without a config. Use one to name routers, add keywords in your own language or keep a skill separate. See [examples/config.example.json](examples/config.example.json).

| Key | What it does |
|---|---|
| `resolution` | Lower = fewer, bigger routers. Higher = more, smaller routers. Default 1.0 |
| `min_group` | Smallest cluster that becomes a router. Default 4 |
| `min_affinity` | How strongly a skill must be tied to its cluster to join it. Default 2.0 |
| `max_files` | Largest bundle in files; bigger routers are split. Default 200, 0 = no limit |
| `exclude` | Extra file globs to leave out, matched inside each skill (for example `canvas-fonts/*`) |
| `standalone` | Skills that are never bundled |
| `groups[].anchors` | The cluster containing these skills gets this router's name and settings, even after new skills are added |
| `groups[].members` | Force skills into this router |
| `groups[].triggers` | Extra keywords added to the router description, for example in another language |
| `groups[].notes` | Notes shown inside the router |
| `overrides` | Replace a skill's description in the output without touching the original |

## Use it as a skill

The repository itself is a skill (`SKILL.md` at the root). Copy the folder into your skills directory and ask your agent to "group my skills" or "I added new skills, update the routers"; it will run the scripts for you.

## Project layout

```
SKILL.md                    the repository as a skill
scripts/build_routers.py    discover, group, write routers, validate, zip, report
scripts/sync_sources.py     pull skills from GitHub into one folder
examples/                   config and sources examples
tests/                      unit tests and benchmark results
```

## Running the tests

```bash
python -m unittest discover -s tests -v
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for every release and the reason behind each change.

## License

MIT
