"""Unit tests for build_routers.py, run on small synthetic skill sets.

    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'scripts', 'build_routers.py')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import build_routers as br  # noqa: E402

COOKING = {
    'bread-baking': 'Bake bread at home: sourdough starters, kneading, proofing and oven temperatures. Also use when the user mentions "sourdough", "loaf", "proofing". See `pastry-making` for sweet doughs.',
    'pastry-making': 'Make pastry and sweet doughs: croissants, puff pastry, tart shells. Also use when the user mentions "croissant", "puff pastry". For savoury bread see `bread-baking`.',
    'cake-decorating': 'Decorate cakes with buttercream, fondant and piping. Also use when the user mentions "frosting", "fondant". Pairs with `pastry-making` and `dessert-plating`.',
    'dessert-plating': 'Plate desserts for restaurants: sauces, garnish, composition. Also use when the user mentions "plating", "garnish". See `cake-decorating`.',
    'baking-science': 'Explain baking chemistry: gluten, leavening, sugar and fat ratios for bread, pastry and cakes. Also use when the user mentions "why did my cake sink". See `bread-baking`.',
}
ASTRONOMY = {
    'telescope-setup': 'Set up and align a telescope: mounts, collimation, polar alignment. Also use when the user mentions "telescope", "collimation". See `astrophotography`.',
    'astrophotography': 'Photograph the night sky: exposure stacking, tracking, processing. Also use when the user mentions "astrophotography", "stacking". Uses `telescope-setup`.',
    'star-charts': 'Read star charts and plan observing sessions by constellation and season. Also use when the user mentions "star chart", "constellation". See `telescope-setup`.',
    'planet-observing': 'Observe planets: best times, filters and magnification. Also use when the user mentions "Jupiter", "Saturn rings". See `star-charts` and `telescope-setup`.',
}
LONERS = {
    'tax-forms': 'Fill in personal tax forms and deadlines. Also use when the user mentions "tax return".',
    'guitar-chords': 'Teach guitar chords and strumming patterns. Also use when the user mentions "chord", "strumming".',
}


def make_skill(root, name, desc, extra_files=None, body='Instructions.'):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'SKILL.md'), 'w', encoding='utf-8') as f:
        f.write(f'---\nname: {name}\ndescription: {json.dumps(desc)}\n---\n\n# {name}\n\n{body}\n')
    for rel, content in (extra_files or {}).items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
    return d


def run(src, out, *args):
    r = subprocess.run([sys.executable, SCRIPT, '--src', src, '--out', out, *args],
                       capture_output=True, text=True)
    return r


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def frontmatter(path):
    with open(path, encoding='utf-8') as f:
        fm, _ = br.parse_frontmatter(f.read())
    return fm


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, 'skills')
        self.out = os.path.join(self.tmp, 'out')
        os.makedirs(self.src)
        for group in (COOKING, ASTRONOMY, LONERS):
            for n, d in group.items():
                make_skill(self.src, n, d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, cfg=None, min_group=4, resolution=1.0):
        skills, _ = br.discover([self.src])
        groups, alone, *_ = br.cluster(skills, cfg or {}, min_group, resolution)
        return [g['members'] for g in groups], alone


class TestDiscovery(Base):
    def test_finds_all_skills(self):
        skills, dups = br.discover([self.src])
        self.assertEqual(len(skills), len(COOKING) + len(ASTRONOMY) + len(LONERS))
        self.assertEqual(dups, [])

    def test_ignores_skills_nested_inside_a_skill(self):
        make_skill(os.path.join(self.src, 'bread-baking', 'examples'), 'nested-copy', 'Should not be found.')
        skills, _ = br.discover([self.src])
        self.assertNotIn('nested-copy', skills)

    def test_duplicate_names_are_reported_once(self):
        other = os.path.join(self.tmp, 'other')
        make_skill(other, 'bread-baking', 'A second skill with the same name.')
        skills, dups = br.discover([self.src, other])
        self.assertEqual(len(dups), 1)
        self.assertIn('sourdough', skills['bread-baking'].desc)

    def test_folded_yaml_description(self):
        d = os.path.join(self.src, 'folded')
        os.makedirs(d)
        with open(os.path.join(d, 'SKILL.md'), 'w', encoding='utf-8') as f:
            f.write('---\nname: folded\ndescription: >\n  First line\n  second line.\n---\nBody\n')
        skills, _ = br.discover([self.src])
        self.assertEqual(skills['folded'].desc, 'First line second line.')


class TestClustering(Base):
    def test_related_skills_form_routers_and_loners_stay_alone(self):
        groups, alone = self.plan()
        self.assertIn(set(COOKING), groups)
        self.assertIn(set(ASTRONOMY), groups)
        self.assertEqual(alone, set(LONERS))

    def test_unrelated_set_is_not_forced_together(self):
        shutil.rmtree(self.src)
        os.makedirs(self.src)
        for n, d in LONERS.items():
            make_skill(self.src, n, d)
        make_skill(self.src, 'bird-watching', 'Identify birds by song and plumage.')
        groups, alone = self.plan()
        self.assertEqual(groups, [])
        self.assertEqual(len(alone), 3)

    def test_hard_file_links_keep_skills_together(self):
        make_skill(self.src, 'tax-helper', 'Helper scripts.', {'scripts/run.py': "open('../tax-forms/data.csv')"})
        groups, _ = self.plan(min_group=4)
        together = [g for g in groups if 'tax-helper' in g]
        self.assertTrue(together and 'tax-forms' in together[0])

    def test_forced_standalone(self):
        groups, alone = self.plan(cfg={'standalone': ['bread-baking']})
        self.assertIn('bread-baking', alone)
        self.assertFalse(any('bread-baking' in g for g in groups))

    def test_works_without_networkx(self):
        saved = sys.modules.get('networkx')
        sys.modules['networkx'] = None
        try:
            groups, alone = self.plan()
        finally:
            if saved is None:
                sys.modules.pop('networkx', None)
            else:
                sys.modules['networkx'] = saved
        self.assertIn(set(COOKING), groups)
        self.assertEqual(alone, set(LONERS))


class TestOutput(Base):
    def build(self, *args):
        r = run(self.src, self.out, *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def tops(self):
        return sorted(d for d in os.listdir(self.out) if os.path.isdir(os.path.join(self.out, d)))

    def test_router_files_are_valid(self):
        self.build()
        self.assertEqual(len(self.tops()), 4)  # 2 routers + 2 loners
        for t in self.tops():
            fm = frontmatter(os.path.join(self.out, t, 'SKILL.md'))
            self.assertEqual(fm['name'], t)
            self.assertTrue(0 < len(fm['description']) <= 1024)

    def test_router_lists_every_member_and_bundles_it(self):
        self.build()
        router = next(t for t in self.tops() if os.path.isdir(os.path.join(self.out, t, 'skills'))
                      and 'bread-baking' in os.listdir(os.path.join(self.out, t, 'skills')))
        text = read_text(os.path.join(self.out, router, 'SKILL.md'))
        for n in COOKING:
            self.assertIn(f'`{n}`', text)
            self.assertTrue(os.path.isfile(os.path.join(self.out, router, 'skills', n, 'SKILL.md')))

    def test_zip_layout(self):
        self.build()
        for t in self.tops():
            with zipfile.ZipFile(os.path.join(self.out, t + '.zip')) as z:
                names = z.namelist()
            self.assertIn(f'{t}/SKILL.md', names)
            self.assertTrue(all(n.startswith(t + '/') for n in names))

    def test_config_anchor_names_router(self):
        cfg = os.path.join(self.tmp, 'cfg.json')
        save_json({'groups': [{'name': 'kitchen', 'anchors': ['bread-baking'], 'triggers': 'Extra words: cuisine.'}]}, cfg)
        self.build('--config', cfg)
        self.assertIn('kitchen', self.tops())
        self.assertIn('cuisine', frontmatter(os.path.join(self.out, 'kitchen', 'SKILL.md'))['description'])

    def test_long_description_is_trimmed_for_standalone(self):
        make_skill(self.src, 'verbose-skill', 'word ' * 400)
        out = self.build()
        self.assertIn('trimmed', out)
        self.assertLessEqual(len(frontmatter(os.path.join(self.out, 'verbose-skill', 'SKILL.md'))['description']), 1024)

    def test_description_override(self):
        cfg = os.path.join(self.tmp, 'cfg.json')
        save_json({'overrides': {'tax-forms': {'description': 'Overridden text.'}}}, cfg)
        self.build('--config', cfg)
        self.assertEqual(frontmatter(os.path.join(self.out, 'tax-forms', 'SKILL.md'))['description'], 'Overridden text.')

    def test_token_report(self):
        out = self.build()
        self.assertIn('always-loaded', out)
        m = load_json(os.path.join(self.out, '.router-manifest.json'))['metrics']
        self.assertLess(m['routed_listing_chars'], m['flat_listing_chars'])


class TestIncrementalBuilds(Base):
    def test_new_skill_joins_existing_router_without_regrouping(self):
        run(self.src, self.out)
        before = load_json(os.path.join(self.out, '.router-manifest.json'))['skills']
        make_skill(self.src, 'meteor-showers', 'Plan meteor shower viewing by date and radiant. See `star-charts` and `planet-observing`. Also use when the user mentions "Perseids".')
        r = run(self.src, self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = load_json(os.path.join(self.out, '.router-manifest.json'))['skills']
        for n, info in before.items():
            self.assertEqual(after[n]['group'], info['group'])
        self.assertEqual(after['meteor-showers']['group'], after['star-charts']['group'])
        self.assertIn("+1 ['meteor-showers']", r.stdout)

    def test_only_changed_outputs_need_reupload(self):
        run(self.src, self.out)
        run(self.src, self.out)
        with open(os.path.join(self.src, 'guitar-chords', 'SKILL.md'), 'a', encoding='utf-8') as f:
            f.write('\nMore.\n')
        r = run(self.src, self.out)
        self.assertIn("re-upload needed : ['guitar-chords']", r.stdout)

    def test_removed_skill_is_reported(self):
        run(self.src, self.out)
        shutil.rmtree(os.path.join(self.src, 'tax-forms'))
        r = run(self.src, self.out)
        self.assertIn("-1 ['tax-forms']", r.stdout)
        self.assertIn('delete from host', r.stdout)


if __name__ == '__main__':
    unittest.main()
