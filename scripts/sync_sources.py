#!/usr/bin/env python3
"""
sync_sources.py - keep skills pulled from GitHub up to date, then hand them to build_routers.py.

sources.json example:
{
  "sources": [
    {"repo": "coreyhaines31/marketingskills", "paths": ["skills/*"]},
    {"repo": "your-name/design-skills", "paths": ["skills/*"], "exclude": ["old-skill"]},
    {"repo": "hardikpandya/stop-slop", "paths": ["."], "as": "stop-slop"}
  ],
  "local": ["~/my-own-skills"]
}

Usage
  python sync_sources.py --sources sources.json --work <dir>
    -> clones or pulls every repo into <dir>/sources, rebuilds <dir>/skills (a flat folder of skills)
       and prints which repos changed since the last sync. Then run:
  python build_routers.py --src <dir>/skills --out <dir>/out --config <config.json>
"""
import argparse, glob, json, os, shutil, subprocess, sys

def sh(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)

def head(path):
    r = sh(['git', 'rev-parse', '--short', 'HEAD'], cwd=path)
    return r.stdout.strip() if r.returncode == 0 else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', required=True)
    ap.add_argument('--work', required=True)
    a = ap.parse_args()
    with open(a.sources, encoding='utf-8') as f:
        cfg = json.load(f)
    src_dir = os.path.join(a.work, 'sources')
    out = os.path.join(a.work, 'skills')
    os.makedirs(src_dir, exist_ok=True)
    report, problems = [], []
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for s in cfg.get('sources', []):
        repo = s['repo']
        url = repo if '://' in repo else f'https://github.com/{repo}.git'
        name = repo.rstrip('/').split('/')[-1].removesuffix('.git')
        dst = os.path.join(src_dir, name)
        before = head(dst) if os.path.isdir(os.path.join(dst, '.git')) else None
        if before:
            r = sh(['git', 'pull', '--ff-only', '-q'], cwd=dst)
        else:
            r = sh(['git', 'clone', '--depth', '1', '-q', url, dst])
        if r.returncode != 0:
            problems.append(f'{repo}: {r.stderr.strip()[:200]}')
            if not os.path.isdir(dst):
                continue
        after = head(dst)
        report.append((repo, before, after))
        excl = set(s.get('exclude', []))
        for pat in s.get('paths', ['.']):
            for p in sorted(glob.glob(os.path.join(dst, pat))):
                if not os.path.isfile(os.path.join(p, 'SKILL.md')):
                    continue
                folder = s.get('as') if pat in ('.', '') else os.path.basename(os.path.normpath(p))
                folder = folder or name
                if folder in excl:
                    continue
                target = os.path.join(out, folder)
                if os.path.exists(target):
                    problems.append(f'{repo}: skill folder "{folder}" already taken, skipped')
                    continue
                shutil.copytree(p, target, symlinks=False, ignore=shutil.ignore_patterns('.git'))
    for loc in cfg.get('local', []):
        loc = os.path.expanduser(loc)
        for p in sorted(glob.glob(os.path.join(loc, '*', 'SKILL.md'))):
            d = os.path.dirname(p)
            target = os.path.join(out, os.path.basename(d))
            if not os.path.exists(target):
                shutil.copytree(d, target, ignore=shutil.ignore_patterns('.git'))
    print(f'Skills assembled: {len(os.listdir(out))} in {out}')
    for repo, b, c in report:
        state = 'new' if not b else ('updated ' + b + ' -> ' + c if b != c else 'no change')
        print(f'  {repo}: {state}')
    for p in problems:
        print('  ! ' + p)

if __name__ == '__main__':
    main()
