#!/usr/bin/env python3
"""
build_routers.py - turn any pile of Agent Skills into a few auto-generated router ("umbrella") skills.

How it works
  1. Discovers every skill (folder with SKILL.md) under the given roots.
  2. Builds a connection graph between skills:
       - hard links  : a skill uses another skill's files (../other/...)  -> must stay together
       - mentions    : a skill names another skill (`other`, "the other skill", see other, /other)
       - similarity  : TF-IDF similarity of names + descriptions
  3. Finds communities in that graph (Louvain). Each big community becomes one router skill;
     small ones stay standalone.
  4. Writes for every router a SKILL.md map generated from the members' own descriptions,
     copies members under <router>/skills/<name>/ (their SKILL.md renamed to INSTRUCTIONS.md so each
     bundle holds exactly one SKILL.md), splits bundles above --max-files, validates and zips everything.

Re-run it whenever skills are added or removed; it reports what changed since the last build.
Only the Python standard library is required (networkx is used when available).

Usage
  python build_routers.py --src <skills_dir> [--src <more_dirs>] --out <out_dir> [--config cfg.json]
                          [--min-group 4] [--resolution 1.0] [--max-files 200] [--exclude GLOB]
                          [--rebalance] [--no-zip] [--dry-run]
"""
import argparse, fnmatch, hashlib, json, math, os, re, shutil, sys, zipfile
from collections import Counter, defaultdict

MAX_DESC = 1024
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
TEXT_EXT = {'.md', '.py', '.js', '.ts', '.mjs', '.cjs', '.json', '.sh', '.txt', '.yaml', '.yml', '.toml', '.html'}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}
# development-only files, not needed at runtime
DEFAULT_EXCLUDE = ['evals/*', 'evals/**', 'tests/*', 'tests/**', 'test/*', 'test/**', '.github/**', '*.coverage', '.coverage']
NESTED_NAME = 'INSTRUCTIONS.md'  # one SKILL.md per bundle
STOP = set("""a an and or the of to for in on with by from at as is are be been being this that these those it its into
over under via vs not no use used uses using user users when where what which who how why can will should would could
also any all each every their them they you your our we i me my mine more most other others than then so such very
just only about after before while within without between across per new existing skill skills want wants wanted
need needs help mentions mention says say like e g eg etc including include includes based make makes create build
get set do does done one two three see work works working run runs whenever someone something anything wants wanting
asks asked trigger triggers apply applies especially always never every-time time times thing things way ways""".split())

# --------------------------------------------------------------------------- parsing

def read(p):
    with open(p, encoding='utf-8', errors='replace') as f:
        return f.read()

def parse_frontmatter(text):
    m = re.match(r'^﻿?---\s*\r?\n(.*?)\r?\n---\s*(\r?\n|$)', text, re.S)
    if not m:
        return {}, text
    raw, body = m.group(1), text[m.end():]
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(raw) or {}
        if isinstance(data, dict):
            return data, body
    except Exception:
        pass
    data, key, buf = {}, None, []
    for line in raw.splitlines():
        km = re.match(r'^([A-Za-z0-9_-]+):\s*(.*)$', line)
        if km and not line.startswith((' ', '\t')):
            if key:
                data[key] = ' '.join(buf).strip()
            key, val = km.group(1), km.group(2).strip()
            buf = [] if val in ('>', '|', '>-', '|-') else [val]
        elif key:
            buf.append(line.strip())
    if key:
        data[key] = ' '.join(buf).strip()
    for k, v in list(data.items()):
        if isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            data[k] = v[1:-1]
    return data, body

def clean_ws(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()

def file_hash(path):
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, path).replace('\\', '/').encode())
            with open(fp, 'rb') as f:
                h.update(f.read())
    return h.hexdigest()[:16]

class Skill:
    def __init__(self, path):
        self.path = path
        self.folder = os.path.basename(os.path.normpath(path))
        self.text = read(os.path.join(path, 'SKILL.md'))
        fm, self.body = parse_frontmatter(self.text)
        self.fm = fm
        self.name = clean_ws(fm.get('name') or self.folder)
        self.desc = clean_ws(fm.get('description'))
        self.hash = file_hash(path)
        self.hard_refs = set()
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                    fp = os.path.join(root, fn)
                    if os.path.getsize(fp) < 400_000:
                        for r in re.findall(r'\.\./([a-z0-9][a-z0-9-]*)/', read(fp)):
                            self.hard_refs.add(r)

def discover(roots):
    skills, dups = {}, []
    for root in roots:
        root = os.path.abspath(root)
        if os.path.isfile(os.path.join(root, 'SKILL.md')):
            cands = [root]
        else:
            cands = []
            for cur, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                if 'SKILL.md' in files and os.path.abspath(cur) != root:
                    cands.append(cur)
                    dirs[:] = []  # never descend into a skill
        for c in cands:
            try:
                s = Skill(c)
            except Exception as e:
                print(f'  ! skipped {c}: {e}', file=sys.stderr)
                continue
            if s.name in skills:
                dups.append((s.name, c, skills[s.name].path))
                continue
            skills[s.name] = s
    return skills, dups

# --------------------------------------------------------------------------- text helpers

LEAD = re.compile(r'^(this skill should be used|use this skill|use this|use when|use for|when the user|when user|'
                  r'when you|this skill|skill for|a skill (for|that))\s*(when|for|to|wants? to|needs?|asks? (to|for|about)|'
                  r'is|has|mentions)?\s*(the user\s*)?(wants? to|needs?)?\s*', re.I)

def summary(desc, limit=150):
    d = desc.strip().strip('"\'')
    d = LEAD.sub('', d).strip()
    d = re.sub(r'^(wants?|needs?)\s+(help|to)\s+(with\s+)?', '', d, flags=re.I).strip()
    d = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', d)[0] if d else d
    d = d.rstrip('.').strip()
    if d:
        d = d[0].upper() + d[1:]
    if len(d) > limit:
        cut = d[:limit].rsplit(' ', 1)[0]
        d = cut.rstrip(',;:-') + '...'
    return d

QUOTE = re.compile(r'(?:(?<=[\s(,:])|^)[\'"“‘]([^\'"”’\n]{3,42}?)[\'"”’](?=[\s,.;:)!?]|$)')

def triggers(desc, n=4):
    out = []
    for q in QUOTE.findall(desc):
        q = q.strip(' .,')
        if q and q.lower() not in (x.lower() for x in out) and not q.lower().startswith(('when ', 'this ', 'use ')):
            out.append(q)
        if len(out) >= n:
            break
    return out

def tokens(s):
    return [w for w in re.findall(r'[a-z0-9][a-z0-9+]*', s.lower()) if w not in STOP and len(w) > 2 and not w.isdigit()]

def tfidf(docs):
    df = Counter()
    toks = {k: tokens(v) for k, v in docs.items()}
    for t in toks.values():
        df.update(set(t))
    n = len(docs)
    vecs = {}
    for k, t in toks.items():
        tf = Counter(t)
        v = {w: (c / len(t)) * math.log((n + 1) / (df[w] + 0.5)) for w, c in tf.items()} if t else {}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[k] = {w: x / norm for w, x in v.items()}
    return vecs

def cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())

# --------------------------------------------------------------------------- graph

def mention_counts(skills):
    names = list(skills)
    out = defaultdict(float)
    for a, s in skills.items():
        t = s.text
        for b in names:
            if a == b:
                continue
            e = re.escape(b)
            pats = [rf'`{e}`', rf'\bthe {e} skill\b', rf'\b{e} skill\b', rf'\bskills?/{e}\b', rf'(?<![\w/.-])/{e}\b',
                    rf'\b(see|use|run|try|invoke|load)\s+(the\s+)?\*{{0,2}}{e}\b']
            if '-' in b:
                pats.append(rf'(?<![\w-]){e}(?![\w-])')
            hits = sum(len(re.findall(p, t, re.I)) for p in pats)
            if hits:
                out[tuple(sorted((a, b)))] += min(hits, 6)
    return out

class DSU:
    def __init__(self, items):
        self.p = {i: i for i in items}
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)

def communities(nodes, edges, resolution, seed=42):
    try:
        import networkx as nx
        g = nx.Graph()
        g.add_nodes_from(nodes)
        for (a, b), w in edges.items():
            g.add_edge(a, b, weight=w)
        return [set(c) for c in nx.community.louvain_communities(g, weight='weight', resolution=resolution, seed=seed)]
    except ImportError:
        # fallback: label propagation, deterministic order
        label = {n: n for n in nodes}
        adj = defaultdict(dict)
        for (a, b), w in edges.items():
            adj[a][b] = w
            adj[b][a] = w
        for _ in range(30):
            changed = False
            for n in sorted(nodes):
                if not adj[n]:
                    continue
                score = defaultdict(float)
                for m, w in adj[n].items():
                    score[label[m]] += w
                best = max(sorted(score), key=lambda k: score[k])
                if score[best] > score.get(label[n], 0) and best != label[n]:
                    label[n] = best
                    changed = True
            if not changed:
                break
        groups = defaultdict(set)
        for n, l in label.items():
            groups[l].add(n)
        return list(groups.values())

def cluster(skills, cfg, min_group, resolution):
    names = sorted(skills)
    docs = {n: (n.replace('-', ' ') + ' ') * 2 + skills[n].desc for n in names}
    vecs = tfidf(docs)
    sim = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sim[(a, b)] = cos(vecs[a], vecs[b])
    ment = mention_counts(skills)

    forced_alone = set(cfg.get('standalone', []))
    pinned = {}  # skill -> group name from config "members"
    for g in cfg.get('groups', []):
        for m in g.get('members', []):
            for n in names:
                if re.fullmatch(m.replace('*', '.*'), n):
                    pinned[n] = g['name']

    edges = defaultdict(float)
    for (a, b), s in sim.items():
        if s >= 0.12:
            edges[(a, b)] += s * 4.0
    for k, c in ment.items():
        edges[k] += c * 1.0
    dsu = DSU(names)
    for n in names:
        for r in skills[n].hard_refs:
            if r in skills and r != n:
                dsu.union(n, r)
                edges[tuple(sorted((n, r)))] += 8.0
    free = [n for n in names if n not in forced_alone and n not in pinned]
    fedges = {k: w for k, w in edges.items() if k[0] in free and k[1] in free}
    comms = communities(free, fedges, resolution)

    # merge communities that are hard-linked
    owner = {}
    for i, c in enumerate(comms):
        for n in c:
            owner[n] = i
    merge = DSU(range(len(comms)))
    for n in free:
        for m in free:
            if n < m and dsu.find(n) == dsu.find(m) and owner[n] != owner[m]:
                merge.union(owner[n], owner[m])
    merged = defaultdict(set)
    for i, c in enumerate(comms):
        merged[merge.find(i)] |= c
    groups = [g for g in merged.values()]

    # config pinned groups
    pg = defaultdict(set)
    for n, g in pinned.items():
        pg[g].add(n)

    # attach fragments smaller than min_group to their most-linked community
    min_aff = cfg.get('min_affinity', 2.0)
    def link(a, b):
        return sum(edges.get(tuple(sorted((x, y))), 0) for x in a for y in b)
    changed = True
    while changed:
        changed = False
        groups.sort(key=lambda g: (len(g), sorted(g)))
        for i, g in enumerate(groups):
            if len(g) >= min_group:
                continue
            others = [(link(g, h), j) for j, h in enumerate(groups) if j != i]
            if not others:
                break
            w, j = max(others)
            if w >= min_aff:
                groups[j] = groups[j] | g
                groups.pop(i)
                changed = True
                break

    # weakly tied members stay standalone
    refined, loose = [], set()
    for g in groups:
        keep = set(g)
        for n in g:
            linked = any(dsu.find(n) == dsu.find(m) for m in g if m != n)
            aff = sum(edges.get(tuple(sorted((n, m))), 0) for m in g if m != n)
            if aff < min_aff and not linked:
                keep.discard(n)
                loose.add(n)
        refined.append(keep)
    groups = [g for g in refined if g]

    result, alone = [], set(forced_alone) | loose
    for g in groups:
        hard_bundle = len({dsu.find(n) for n in g}) < len(g)  # contains linked skills
        if len(g) >= min_group or (hard_bundle and len(g) >= 2):
            result.append({'members': g, 'cfg': None})
        else:
            alone |= g
    for gname, mem in pg.items():
        result.append({'members': mem, 'cfg': gname})
    return result, alone, sim, ment, edges

def sticky(old, skills, fresh_groups, fresh_alone, edges, cfg, min_group):
    """Keep the previous layout; place only new skills."""
    forced_alone = set(cfg.get('standalone', []))
    kept = defaultdict(set)
    old_alone = set()
    for n, info in old['skills'].items():
        if n in skills:
            if info.get('group'):
                kept[info['group']].add(n)
            else:
                old_alone.add(n)
    new = sorted(n for n in skills if n not in old['skills'])
    w = lambda x, y: edges.get(tuple(sorted((x, y))), 0)
    min_aff = cfg.get('min_affinity', 2.0)
    unplaced = []
    for n in new:
        if n in forced_alone:
            old_alone.add(n)
            continue
        hard = [g for g, mem in kept.items() if any(r in mem for r in skills[n].hard_refs) or
                any(n in skills[m].hard_refs for m in mem)]
        scores = {g: sum(w(n, m) for m in mem) for g, mem in kept.items()}
        best = hard[0] if hard else (max(scores, key=scores.get) if scores else None)
        if best and (hard or scores[best] >= min_aff):
            kept[best].add(n)
        else:
            unplaced.append(n)
    # new skills forming their own community become a new group
    pool = set(unplaced) | old_alone
    for g in fresh_groups:
        part = g['members'] & pool
        if len(part) >= min_group and part & set(unplaced) and not part & forced_alone:
            kept[f'__new_{len(kept)}'] = part
            pool -= part
    by_cfg = {g['name'] for g in cfg.get('groups', [])}
    groups = [{'members': mem, 'cfg': g if g in by_cfg else None, 'old_name': None if g.startswith('__new_') else g}
              for g, mem in kept.items() if mem]
    return groups, pool

# --------------------------------------------------------------------------- file selection

def excluded(rel, patterns):
    rel = rel.replace('\\', '/')
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(os.path.basename(rel), p) for p in patterns)

def member_files(skill, patterns):
    out = []
    for root, dirs, files in os.walk(skill.path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, skill.path)
            if not excluded(rel, patterns):
                out.append(rel)
    return out

def copy_skill(skill, dst, patterns, nested=False):
    for rel in member_files(skill, patterns):
        target = os.path.join(dst, rel)
        if nested and rel.replace('\\', '/') == 'SKILL.md':
            target = os.path.join(dst, NESTED_NAME)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(skill.path, rel), target)
    if nested:  # update references to the renamed file
        for root, _, files in os.walk(dst):
            for fn in files:
                if fn.endswith('.md'):
                    fp = os.path.join(root, fn)
                    txt = read(fp)
                    if 'SKILL.md' in txt:
                        with open(fp, 'w', encoding='utf-8', newline='') as f:
                            f.write(txt.replace('SKILL.md', NESTED_NAME))

# --------------------------------------------------------------------------- splitting oversized routers

def pack(bundles, count, max_files, edges):
    """Greedy fallback: grow parts from the most-linked bundles while they fit."""
    link = lambda a, b: sum(edges.get(tuple(sorted((x, y))), 0) for x in a for y in b)
    left = sorted(bundles, key=lambda b: (-len(b), sorted(b)))
    parts = []
    while left:
        cur = set(left.pop(0))
        while True:
            fits = [b for b in left if count(cur | b) <= max_files]
            if not fits:
                break
            best = max(fits, key=lambda b: (link(cur, b), -len(b), sorted(b)))
            cur |= best
            left.remove(best)
        parts.append(cur)
    return parts

def split_oversized(members, skills, edges, patterns, max_files, resolution):
    """Split a group whose bundle would exceed max_files into smaller communities."""
    count = lambda g: 1 + sum(len(member_files(skills[n], patterns)) for n in g)
    if not max_files or count(members) <= max_files:
        return [set(members)], []
    dsu = DSU(list(members))
    for n in members:
        for r in skills[n].hard_refs:
            if r in members and r != n:
                dsu.union(n, r)
    pending, done = [set(members)], []
    while pending:
        g = pending.pop()
        if count(g) <= max_files:
            done.append(g)
            continue
        parts = None
        for r in (resolution, resolution * 1.5, resolution * 2, resolution * 3, resolution * 5, resolution * 8, resolution * 13):
            sub = {k: w for k, w in edges.items() if k[0] in g and k[1] in g}
            comms = communities(sorted(g), sub, r)
            merged = defaultdict(set)  # hard-linked skills must stay in one part
            for c in comms:
                merged[min(dsu.find(n) for n in c)] |= c
            fused = DSU(list(merged))
            keys = list(merged)
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    if {dsu.find(n) for n in merged[a]} & {dsu.find(n) for n in merged[b]}:
                        fused.union(a, b)
            final = defaultdict(set)
            for k in keys:
                final[fused.find(k)] |= merged[k]
            if len(final) > 1:
                parts = list(final.values())
                break
        if not parts:
            bundles = defaultdict(set)
            for n in g:
                bundles[dsu.find(n)].add(n)
            if len(bundles) == 1:
                return None, sorted(g)  # one file-linked bundle, cannot split
            parts = pack(list(bundles.values()), count, max_files, edges)
        pending.extend(parts)
    # greedily re-merge parts that still fit, most-linked first
    link = lambda a, b: sum(edges.get(tuple(sorted((x, y))), 0) for x in a for y in b)
    while len(done) > 1:
        best = None
        for i in range(len(done)):
            for j in range(i + 1, len(done)):
                if count(done[i] | done[j]) <= max_files:
                    score = (link(done[i], done[j]) + 0.001) / (len(done[i]) * len(done[j]))
                    if best is None or score > best[0]:
                        best = (score, i, j)
        if not best:
            break
        _, i, j = best
        done[i] = done[i] | done[j]
        done.pop(j)
    return [g for g in done if len(g) > 1], [n for g in done if len(g) == 1 for n in g]

def part_name(base, members, skills, siblings, used):
    """Name a split part by its most distinctive word."""
    def words(group):
        c = Counter()
        for n in group:
            c.update(set(tokens(n.replace('-', ' ') + ' ' + n.replace('-', ' ') + ' ' + skills[n].desc)))
        return c
    mine, allw = words(members), words(siblings)
    skip = set(base.split('-')) | {'marketing', 'skill', 'skills', 'user', 'content', 'page', 'pages'}
    ranked = sorted(((mine[w] / len(members)) * (mine[w] / allw[w]), w) for w in mine
                    if w not in skip and mine[w] >= 2 and len(w) > 2)
    for _, w in reversed(ranked):
        cand = f'{base}-{w}'
        if cand not in used and len(cand) <= 64:
            return cand
    i = 2
    while f'{base}-{i}' in used:
        i += 1
    return f'{base}-{i}'

# --------------------------------------------------------------------------- naming & writing

def auto_name(members, used):
    c = Counter()
    for n in members:
        for p in n.split('-'):
            if p not in STOP and len(p) > 1:
                c[p] += 1
    ranked = sorted(c.items(), key=lambda x: (-x[1], x[0]))
    top = [w for w, k in ranked if k >= 2] or [w for w, _ in ranked[:1]]
    cands = []
    if len(top) >= 2 and c[top[1]] >= max(2, c[top[0]] // 2):
        cands.append(f'{top[0]}-{top[1]}-toolkit')
    cands += [f'{w}-toolkit' for w, _ in ranked]
    for cand in cands:
        if cand not in used:
            return cand
    i = 1
    while f'skill-group-{i}' in used:
        i += 1
    return f'skill-group-{i}'

def pick_cfg(group, cfg):
    by_name = {g['name']: g for g in cfg.get('groups', [])}
    if group['cfg']:
        return by_name[group['cfg']]
    best, score = None, 0
    for g in cfg.get('groups', []):
        a = sum(1 for x in g.get('anchors', []) if x in group['members'])
        if a > score:
            best, score = g, a
    return best

def topic_words(members, skills, k=4):
    c = Counter()
    for n in members:
        c.update(set(tokens(n.replace('-', ' ') + ' ' + skills[n].desc)))
    return [w for w, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:k]]

def router_description(gcfg, members, skills):
    lead = (gcfg or {}).get('title_en') or ', '.join(topic_words(members, skills))
    extra = (gcfg or {}).get('triggers', '')
    order = sorted(members)
    names = {n: n.replace('-', ' ') for n in order}
    trig = {}
    for n in order:
        tr = triggers(skills[n].desc, 1)
        trig[n] = tr[0] if tr else ' '.join(summary(skills[n].desc, 80).split()[:6]).rstrip('.,;:')
    head = f'Router for {len(members)} specialist skills' + (f' on {lead}' if lead else '') + \
           '. Use it first for any task in this area; it maps the request to the right sub-skill. Covers: '
    tail = f'. {extra}' if extra else ''
    room = MAX_DESC - len(head) - len(tail) - 5
    parts = dict(names)
    body = ', '.join(parts[n] for n in order)
    for n in order:  # add trigger phrases while within the limit
        tr = trig[n]
        if tr and tr.lower() not in parts[n].lower():
            trial = dict(parts); trial[n] = f'{parts[n]} ({tr})'
            cand = ', '.join(trial[m] for m in order)
            if len(cand) <= room:
                parts, body = trial, cand
    if len(body) > room:
        body = body[:room].rsplit(',', 1)[0]
    return (head + body + tail).replace('\n', ' ')[:MAX_DESC]

def write_router(name, gcfg, members, skills, sim, out_dir, patterns):
    root = os.path.join(out_dir, name)
    os.makedirs(os.path.join(root, 'skills'))
    for n in sorted(members):
        dst = os.path.join(root, 'skills', skills[n].folder)
        copy_skill(skills[n], dst, patterns, nested=True)
        if getattr(skills[n], 'overridden', False):
            set_desc(os.path.join(dst, NESTED_NAME), skills[n].desc)
    desc = router_description(gcfg, members, skills)
    title = (gcfg or {}).get('title') or name.replace('-', ' ').title()
    lines = ['---', f'name: {name}', 'description: ' + json.dumps(desc, ensure_ascii=False), '---', '',
             f'# {title}', '',
             f'This is a router: an index of {len(members)} complete skills bundled under `skills/`. '
             'It was generated automatically from their own descriptions.', '',
             '## How to use', '',
             '1. Pick the ONE sub-skill below that best fits the request (two at most if the task clearly spans both). '
             'Match on the summary first, then the trigger phrases.',
             f'2. Read `skills/<folder>/{NESTED_NAME}` and follow it exactly as if it were installed on its own.',
             '3. Paths inside a sub-skill (`references/`, `scripts/`, `../<sibling>/`) are relative to that sub-skill\'s folder.',
             f'4. When a sub-skill says "see/use the X skill" and X is listed here, open `skills/X/{NESTED_NAME}`.',
             '5. Never read all sub-skills; load only what the task needs. If nothing fits, do not force one.', '']
    if (gcfg or {}).get('notes'):
        lines += ['## Notes', ''] + [f'- {x}' for x in gcfg['notes']] + ['']
    lines += ['## Sub-skills', '']
    for n in sorted(members):
        s = skills[n]
        tr = triggers(s.desc)
        line = f'- `{s.folder}` - {summary(s.desc)}'
        if tr:
            line += (' ' if line.endswith('...') else '. ') + 'Triggers: ' + ', '.join(f'"{t}"' for t in tr) + '.'
        lines.append(line)
    pairs = sorted(((sim.get(tuple(sorted((a, b))), 0), a, b) for a in members for b in members if a < b), reverse=True)
    pairs = [p for p in pairs if p[0] >= 0.28][:10]
    if pairs:
        lines += ['', '## Easily confused - decide carefully', '']
        for _, a, b in pairs:
            lines.append(f'- `{a}`: {summary(skills[a].desc, 90)} | `{b}`: {summary(skills[b].desc, 90)}')
    lines.append('')
    with open(os.path.join(root, 'SKILL.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    return desc

def set_desc(skill_md, desc):
    t = read(skill_md)
    t = re.sub(r'(?ms)^description:.*?(?=^[A-Za-z_-]+:|^---)', lambda m: 'description: ' + json.dumps(desc, ensure_ascii=False) + '\n', t, count=1)
    with open(skill_md, 'w', encoding='utf-8', newline='\n') as f:
        f.write(t)

def write_standalone(s, out_dir, warnings, patterns):
    dst = os.path.join(out_dir, s.folder)
    copy_skill(s, dst, patterns)
    if getattr(s, 'overridden', False):
        set_desc(os.path.join(dst, 'SKILL.md'), s.desc)
    if len(s.desc) > MAX_DESC:
        p = os.path.join(dst, 'SKILL.md')
        t = read(p)
        short = s.desc[:MAX_DESC - 3].rsplit(' ', 1)[0] + '...'
        t = re.sub(r'(?ms)^description:.*?(?=^[A-Za-z_-]+:|^---)', 'description: ' + json.dumps(short, ensure_ascii=False) + '\n', t, count=1)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(t)
        warnings.append(f'{s.name}: description was {len(s.desc)} chars, trimmed to fit {MAX_DESC}')

def zip_dir(path):
    zp = path.rstrip('/\\') + '.zip'
    base = os.path.basename(path.rstrip('/\\'))
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                z.write(fp, base + '/' + os.path.relpath(fp, path).replace('\\', '/'))
    return zp

# --------------------------------------------------------------------------- metrics

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def est_tokens(chars):
    return round(chars / 3.6)

def listing_chars(name, desc):
    return len(name) + len(desc) + 12  # name + description + list formatting

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', action='append', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--config')
    ap.add_argument('--min-group', type=int, default=None)
    ap.add_argument('--resolution', type=float, default=None)
    ap.add_argument('--no-zip', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--rebalance', action='store_true', help='ignore the previous build and recluster everything')
    ap.add_argument('--max-files', type=int, default=None,
                    help='split routers whose bundle would exceed this many files (default 200, 0 = no limit)')
    ap.add_argument('--exclude', action='append', default=[], help='extra glob of files to leave out (repeatable)')
    a = ap.parse_args()
    cfg = load_json(a.config) if a.config else {}
    a.resolution = a.resolution if a.resolution is not None else cfg.get('resolution', 1.0)
    a.min_group = a.min_group if a.min_group is not None else cfg.get('min_group', 4)
    a.max_files = a.max_files if a.max_files is not None else cfg.get('max_files', 200)
    patterns = DEFAULT_EXCLUDE + cfg.get('exclude', []) + a.exclude
    skills, dups = discover(a.src)
    if not skills:
        sys.exit('No skills found.')
    print(f'Found {len(skills)} skills.')
    for n, ov in cfg.get('overrides', {}).items():
        if n in skills and ov.get('description'):
            skills[n].desc = clean_ws(ov['description'])
            skills[n].overridden = True
            skills[n].hash = hashlib.sha256((skills[n].hash + skills[n].desc).encode()).hexdigest()[:16]
    for n, p, keep in dups:
        print(f'  ! duplicate name "{n}" at {p} (kept {keep})')
    groups, alone, sim, ment, edges = cluster(skills, cfg, a.min_group, a.resolution)

    manifest_path = os.path.join(a.out, '.router-manifest.json')
    old = load_json(manifest_path) if os.path.exists(manifest_path) else None
    if old and not a.rebalance:
        groups, alone = sticky(old, skills, groups, alone, edges, cfg, a.min_group)
        print('Sticky mode: existing groups kept, new skills placed by affinity (use --rebalance to recluster).')

    # merge groups mapped to the same configured router
    merged, out_groups = {}, []
    for g in groups:
        gc = pick_cfg(g, cfg)
        key = (gc or {}).get('name')
        if key and key in merged:
            merged[key]['members'] |= g['members']
        else:
            g = dict(g, cfg=key or g.get('cfg'))
            out_groups.append(g)
            if key:
                merged[key] = g
    groups = out_groups

    used, plan = set(alone), []
    for g in sorted(groups, key=lambda g: -len(g['members'])):
        gcfg = pick_cfg(g, cfg)
        name = (gcfg or {}).get('name') or g.get('old_name') or auto_name(g['members'], used)
        if name in used:
            name = auto_name(g['members'], used)
        used.add(name)
        parts, rest = split_oversized(g['members'], skills, edges, patterns, a.max_files, a.resolution)
        if parts is None:
            sys.exit(f'Router "{name}" cannot fit in {a.max_files} files because these skills are file-linked: '
                     f'{", ".join(rest)}. Add "exclude" globs for large asset folders or raise --max-files.')
        if len(parts) == 1 and not rest:
            plan.append((name, gcfg, parts[0]))
            continue
        used.discard(name)
        print(f'  note: "{name}" exceeds {a.max_files} files, split into {len(parts)} routers')
        for part in sorted(parts, key=lambda p: -len(p)):
            pname = part_name(name, part, skills, g['members'], used)
            used.add(pname)
            pcfg = dict(gcfg or {}, name=pname)
            if gcfg and gcfg.get('title'):
                pcfg['title'] = f"{gcfg['title']} - {pname[len(name) + 1:]}"
            pcfg.pop('title_en', None)
            plan.append((pname, pcfg, part))
        alone |= set(rest)

    print('\nPlan:')
    for name, _, mem in plan:
        print(f'  [router] {name} ({len(mem)}): ' + ', '.join(sorted(mem)))
    print(f'  [standalone] ({len(alone)}): ' + ', '.join(sorted(alone)))
    if a.dry_run:
        return

    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    os.makedirs(a.out)
    warnings, top = [], []
    for name, gcfg, mem in plan:
        if not NAME_RE.match(name):
            sys.exit(f'Invalid router name: {name}')
        desc = write_router(name, gcfg, mem, skills, sim, a.out, patterns)
        top.append((name, desc, os.path.join(a.out, name, 'SKILL.md')))
    for n in sorted(alone):
        s = skills[n]
        if not NAME_RE.match(s.name):
            warnings.append(f'{s.name}: name is not lowercase-hyphen, some hosts may reject it')
        write_standalone(s, a.out, warnings, patterns)
        top.append((s.name, s.desc[:MAX_DESC], os.path.join(a.out, s.folder, 'SKILL.md')))

    # validation
    errors = []
    for name, desc, p in top:
        fm, _ = parse_frontmatter(read(p))
        if clean_ws(fm.get('name')) != name:
            errors.append(f'{name}: name mismatch in SKILL.md')
        if len(clean_ws(fm.get('description'))) > MAX_DESC:
            errors.append(f'{name}: description too long')
        if not clean_ws(fm.get('description')):
            errors.append(f'{name}: empty description')
    for name, _, p in top:
        d = os.path.dirname(p)
        files = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs]
        if sum(1 for f in files if os.path.basename(f) == 'SKILL.md') != 1:
            errors.append(f'{name}: must contain exactly one SKILL.md')
        if a.max_files and len(files) > a.max_files:
            errors.append(f'{name}: {len(files)} files, limit is {a.max_files}')
    for name, _, mem in plan:
        for n in mem:
            for r in skills[n].hard_refs:
                if r in skills and r not in mem:
                    errors.append(f'{name}/{n} links ../{r}/ but {r} is not in the same router')

    zips = []
    if not a.no_zip:
        for name, _, p in top:
            zips.append(zip_dir(os.path.dirname(p)))

    flat = sum(listing_chars(s.name, s.desc) for s in skills.values())
    routed = sum(listing_chars(n, d) for n, d, _ in top)
    router_sizes = {n: len(read(p)) for n, _, p in top if n in {x[0] for x in plan}}
    tops = {}
    for n, _, p in top:
        h = hashlib.sha256(read(p).encode())
        for m in sorted(next((mem for g, _, mem in plan if g == n), {n})):
            h.update(skills[m].hash.encode())
        tops[n] = h.hexdigest()[:16]
    manifest = {
        'tops': tops,
        'skills': {n: {'hash': s.hash, 'group': next((g for g, _, m in plan if n in m), None)} for n, s in skills.items()},
        'metrics': {'skills': len(skills), 'top_level': len(top), 'flat_listing_chars': flat, 'routed_listing_chars': routed,
                    'flat_listing_tokens_est': est_tokens(flat), 'routed_listing_tokens_est': est_tokens(routed),
                    'router_skill_md_chars': router_sizes},
    }
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)

    print('\nResult:')
    print(f'  top-level skills : {len(skills)} -> {len(top)}')
    print(f'  always-loaded    : ~{est_tokens(flat)} -> ~{est_tokens(routed)} tokens per conversation '
          f'({100 - round(100 * routed / flat)}% less)')
    for n, c in router_sizes.items():
        print(f'  router map {n}: ~{est_tokens(c)} tokens, read only when that area is used')
    if old:
        olds, news = set(old['skills']), set(skills)
        added, removed = sorted(news - olds), sorted(olds - news)
        changed = sorted(n for n in news & olds if old['skills'][n]['hash'] != skills[n].hash)
        moved = sorted(n for n in news & olds if old['skills'][n]['group'] != manifest['skills'][n]['group'])
        reup = sorted(n for n in tops if old.get('tops', {}).get(n) != tops[n])
        gone = sorted(set(old.get('tops', {})) - set(tops))
        print(f'  re-upload needed : {reup or "nothing"}' + (f' | delete from host: {gone}' if gone else ''))
        print(f'  since last build : +{len(added)} {added} | -{len(removed)} {removed} | changed {changed} | regrouped {moved}')
    for w in warnings:
        print('  warning:', w)
    for e in errors:
        print('  ERROR:', e)
    if zips:
        print(f'  zips             : {len(zips)} in {a.out}')
    sys.exit(1 if errors else 0)

if __name__ == '__main__':
    main()
