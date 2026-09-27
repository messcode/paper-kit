"""Integration tests use the kit-resolved Pandoc; all manuscript data is temporary."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paperkit', ROOT / 'paperkit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
PANDOC = kit.resolve_pandoc(quiet=True)[0]
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

@unittest.skipUnless(PANDOC, 'run paperkit.py setup first')
class CosbIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paperkit cosb ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('paperkit.py', 'build_docx.sh'):
            shutil.copy2(ROOT / name, self.root / name)
        for name in ('journals', 'styles', 'filters'):
            shutil.copytree(ROOT / name, self.root / name)
        for old, new in [('citations.md', 'manuscript.md'), ('references.bib', 'references.bib'), ('reference-annotations.json', 'reference-annotations.json')]:
            shutil.copy2(ROOT / 'validation/cosb' / old, self.root / new)
        (self.root / 'metadata.yaml').write_text('bibliography: references.bib\nlink-citations: false\n')
        (self.root / 'paperkit.json').write_text('{"journal":"cosb"}')
        self.env = dict(os.environ, PAPERKIT_PANDOC=PANDOC)
        self.env.pop('JOURNAL', None)

    def command(self, *args, ok=True):
        result = subprocess.run([os.sys.executable, 'paperkit.py', *args], cwd=self.root, env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def document(self):
        with ZipFile(self.root / 'output/manuscript.docx') as archive:
            return ET.fromstring(archive.read('word/document.xml'))

    def test_citations_annotations_and_word_layout(self):
        self.command('build', '--no-appendix')
        doc = self.document()
        paragraphs = [''.join(p.itertext()).strip() for p in doc.findall('.//w:p', NS)]
        body = paragraphs[2]
        self.assertIn('[1]', body)
        self.assertIn('[2,3]', body)
        self.assertNotIn('*', body)
        self.assertEqual(paragraphs.count('References and recommended reading'), 1)
        refs = [p for p in paragraphs if p.startswith('[')]
        normalize = lambda s: ' '.join(s.replace('–', '-').split())
        self.assertEqual(normalize(refs[0]), '[1] Van der Geer J, Hanraads JAJ, Lupton RA. The art of writing a scientific article. J Sci Commun 2020;163:51-9. https://doi.org/10.1016/j.sc.2020.00372.')
        self.assertTrue(refs[1].startswith('[2]*.'))
        self.assertIn('Zeta F, et al.', refs[1])
        self.assertNotIn('Eta G', refs[1])
        self.assertTrue(refs[2].startswith('[3]**.'))
        self.assertNotIn('et al.', refs[2])
        self.assertIn('Synthetic annotation of special interest; not a scientific claim.', paragraphs)
        self.assertIn('Synthetic annotation of outstanding interest; not a scientific claim.', paragraphs)
        self.assertFalse(doc.findall('.//w:vertAlign[@w:val="superscript"]', NS))
        for cols in doc.findall('.//w:cols', NS):
            self.assertEqual(cols.get('{%s}num' % NS['w'], '1'), '1')

    def test_cli_and_wrapper_override(self):
        self.assertIn('styles/elsevier-vancouver.csl', self.command('build', '--dry-run').stdout)
        for args in [('build', '--journal', 'nature', '--dry-run'), ('--journal', 'nature', 'build', '--dry-run')]:
            self.assertIn('journals/nature/nature.csl', self.command(*args).stdout)
        if os.name != 'nt':
            result = subprocess.run(['sh', 'build_docx.sh', '--dry-run'], cwd=self.root, env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('styles/elsevier-vancouver.csl', result.stdout)
        self.env['JOURNAL'] = 'nature'
        self.assertIn('journals/nature/nature.csl', self.command('build', '--dry-run').stdout)
        self.assertIn('styles/elsevier-vancouver.csl', self.command('build', '--journal', 'cosb', '--dry-run').stdout)

    def test_draft_without_annotations_and_automatic_heading(self):
        (self.root / 'reference-annotations.json').unlink()
        p = self.root / 'manuscript.md'
        p.write_text(p.read_text().replace('# References\n', ''))
        result = self.command('build', '--no-appendix')
        self.assertIn('target at least 1', result.stderr)
        text = ''.join(self.document().itertext())
        self.assertEqual(text.count('References and recommended reading'), 1)
        self.assertNotIn('[2]*', text)

    def test_invalid_annotations_rejected(self):
        p = self.root / 'reference-annotations.json'
        data = json.loads(p.read_text())
        changes = [lambda d: d['reference-annotations']['seven'].update(interest='***'),
                   lambda d: d['reference-annotations']['seven'].update(text=''),
                   lambda d: d['reference-annotations']['seven'].update(published='2023-01-01'),
                   lambda d: d.update({'review-period-start':'2023-01-01'}),
                   lambda d: d.pop('review-period-end')]
        for change in changes:
            d = copy.deepcopy(data); change(d); p.write_text(json.dumps(d))
            self.assertIn('invalid annotations', self.command('build', '--dry-run', ok=False).stderr)

    def test_reordering_preserves_key_based_annotations(self):
        (self.root / 'manuscript.md').write_text('First [@six], then [@example], then [@seven].\n')
        self.command('build', '--no-appendix')
        text = ''.join(self.document().itertext())
        self.assertIn('[1]**.', text)
        self.assertIn('[3]*.', text)
        self.assertNotIn('[2]*', text)

if __name__ == '__main__':
    unittest.main()
