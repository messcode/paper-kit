import importlib.util
import json
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paperkit', ROOT / 'paperkit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class WordCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pandoc = kit.resolve_pandoc(quiet=True)[0]
        if not cls.pandoc:
            raise unittest.SkipTest('Pandoc required')

    def count(self, text):
        text = re.sub(r'(?m)^(#{1,6} .+)$', r'\n\1\n', text)
        result = subprocess.run([self.pandoc, '-f', 'markdown', '-t', 'json'],
                                input=text, text=True, capture_output=True, check=True)
        return kit.count_manuscript(json.loads(result.stdout))

    def test_sections_and_inline_citations(self):
        counts, _ = self.count('''---
title: Paper title
abstract: Metadata summary
---
## Abstract
Three abstract words.
# Introduction
Two words [@Example].
## Detail
One **bold** word.
# References and recommended reading
Five words in reference annotation.
''')
        self.assertEqual(counts['body'], 7)
        self.assertEqual(counts['abstract'], 5)
        self.assertEqual(counts['references'], 5)
        self.assertEqual(counts['front-matter'], 2)

    def test_figures_tables_boxes_and_explicit_legends(self):
        counts, _ = self.count('''![Three caption words.](image.png)

::: {wordcount="figure-legends"}
Two words.
:::

| First | Second |
|---|---|
| One | Two |

: Table caption

::: box
Box prose.
:::
''')
        self.assertEqual(counts['figure-legends'], 5)
        self.assertEqual(counts['body'], 8)

    def test_scope_resumes_and_refs_div(self):
        counts, _ = self.count('''# Introduction
Body.
## Figure legends
Caption here.
### Detail
More caption.
## Discussion
Body again.

::: {#refs}
Excluded references.
:::
''')
        self.assertEqual(counts['body'], 5)
        self.assertEqual(counts['figure-legends'], 5)
        self.assertEqual(counts['references'], 2)

    def test_review_warnings_and_tokens(self):
        counts, warnings = self.count("State-of-the-art don't 2026. $x+y$ TODO.\n\n```{=latex}\nVisible raw text\n```\n")
        self.assertEqual(counts['body'], 5)
        self.assertTrue(any('Raw markup' in x for x in warnings))
        self.assertTrue(any('TODO' in x for x in warnings))
        self.assertTrue(any('math' in x for x in warnings))

    def test_cli_boundary_and_error(self):
        with tempfile.TemporaryDirectory(prefix='word count ') as directory:
            source = Path(directory) / 'sample.md'
            source.write_text('One two three.')
            command = ['python3', str(ROOT / 'paperkit.py'), 'wordcount', '--source', str(source), '--json']
            for limit, status, code in [(3, 'within-limit', 0), (2, 'over-limit', 1)]:
                result = subprocess.run(command + ['--limit', str(limit)], capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], status)
            result = subprocess.run(command + ['--limit', '0'], capture_output=True)
            self.assertEqual(result.returncode, 2)
        with self.assertRaises(kit.Failure):
            self.count('::: {wordcount="typo"}\nProse\n:::')


if __name__ == '__main__':
    unittest.main()
