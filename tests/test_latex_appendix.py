"""CLI regression tests for the optional LaTeX appendix."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path("journals/nature/templates/appendix.tex")


class LatexAppendixTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        shutil.copy2(ROOT / "paperkit.py", self.root)
        (self.root / TEMPLATE).parent.mkdir(parents=True)
        shutil.copy2(ROOT / TEMPLATE, self.root / TEMPLATE)
        self.appendix = self.root / "appendix.tex"

    def run_new(self, *options):
        result = subprocess.run(
            [sys.executable, "paperkit.py", "--journal", "nature", "new", *options],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_skips_latex_appendix(self):
        self.run_new()
        self.assertFalse(self.appendix.exists())

    def test_opt_in_copies_template(self):
        self.run_new("--latex-appendix")
        self.assertEqual(self.appendix.read_bytes(), (ROOT / TEMPLATE).read_bytes())

    def test_force_preserves_edited_appendix(self):
        self.run_new("--latex-appendix")
        draft = b"% Edited manuscript appendix\r\n"
        self.appendix.write_bytes(draft)
        self.run_new("--force", "--latex-appendix")
        self.assertEqual(self.appendix.read_bytes(), draft)
