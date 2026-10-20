---
name: skill-router-builder
description: Builds and updates router (umbrella) skills from any large skill collection so only a few short descriptions load per conversation instead of dozens. Use when the user has many skills installed, wants to bundle, group, deduplicate or slim down skills, add new skills to existing routers, update skills pulled from GitHub, or prepare skill ZIPs for upload.
---

# Skill Router Builder

Turns a pile of skills into a few auto-generated router skills. Each router's SKILL.md is a map written from its members' own descriptions; members are bundled unchanged under `<router>/skills/<name>/`. Nothing is hard-coded, so it works on any skill set.

Scripts (Python 3 standard library; `networkx` and `git` are used when available):
- `scripts/build_routers.py` - discover, cluster, write routers, validate, zip, report token savings.
- `scripts/sync_sources.py` - clone or pull skills listed in a `sources.json` from GitHub into one flat folder.
- `examples/` - a config and a sources file to start from.

## Workflows

### First build
1. Put the skills in one folder (or pass several `--src`). For GitHub skills write a `sources.json` and run
   `python scripts/sync_sources.py --sources sources.json --work WORK`, which fills `WORK/skills`.
2. Preview: `python scripts/build_routers.py --src WORK/skills --out WORK/out --dry-run`.
3. If the grouping looks wrong, change the config rather than editing the output. Lower `--resolution` gives fewer, larger routers; higher gives more, smaller ones.
4. Build (drop `--dry-run`, add `--config cfg.json`). Exit code 1 means validation errors; fix them before uploading.
5. Read one router SKILL.md and the "Result" block, then report: top-level count before/after, always-loaded tokens before/after, warnings.

### Adding, removing or updating skills
Run the same command with the same `--out`. The `.router-manifest.json` in the output keeps the previous layout:
- existing skills stay in their routers; a new skill joins the router it is most connected to, several related new skills form a new router, anything else stays standalone;
- the report lists added / removed / changed skills and **re-upload needed** (only those ZIPs must be uploaded again) and routers to delete from the host;
- `--rebalance` reclusters everything from scratch.
For GitHub sources run `sync_sources.py` first; it prints which repositories changed upstream.

### Installing the output
Each `WORK/out/*.zip` is one skill (root folder = skill name, SKILL.md inside) for hosts that take ZIP uploads. If the host refuses a name that already exists, delete the old skill first. Hosts that read a skills folder can take the output folders directly.

## Config (all keys optional)
```json
{
  "resolution": 0.7, "min_group": 4, "min_affinity": 2.0,
  "standalone": ["skill-that-must-stay-separate"],
  "groups": [{"name": "marketing", "anchors": ["copywriting", "ads"], "members": ["image"],
              "title": "Marketing Router", "title_en": "marketing, ads and growth",
              "triggers": "Extra trigger words, for example keywords in another language.",
              "notes": ["shown in the router body"]}],
  "overrides": {"some-skill": {"description": "replacement description used in the output copy"}}
}
```
- `anchors`: the auto-found group containing these skills gets this name and description; survives new skills being added.
- `members`: force skills into that router. `standalone`: never bundle these (general-purpose skills such as a writing-style skill).
- `triggers`: add words in the user's own language here; routers are matched by description.

## How grouping works
A graph links skills by hard file links (`../other/`, always kept together), explicit mentions of each other, and TF-IDF similarity of names and descriptions. Louvain community detection finds clusters; clusters smaller than `min_group` and weakly tied members (`min_affinity`) stay standalone, so unrelated skills are never forced together. Router descriptions stay under 1024 characters and list member names with their main trigger phrase; the body adds per-skill summaries, trigger phrases and an "easily confused" list of near-duplicate pairs.
