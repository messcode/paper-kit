"""Exercise independent Word layout and CSL selection with actual DOCX output."""
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
spec = importlib.util.spec_from_file_location("paperkit", ROOT / "paperkit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
PANDOC = kit.resolve_pandoc(quiet=True)[0]
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{%s}" % NS["w"]
REFERENCE = "templates/manuscript/pandoc-reference.docx"


@unittest.skipUnless(PANDOC, "run paperkit.py setup first")
class IndependentDocxStyles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="paperkit independent styles ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(ROOT / "paperkit.py", self.root)
        for name in ("journals", "styles", "filters", "templates"):
            shutil.copytree(ROOT / name, self.root / name)
        shutil.copy2(ROOT / "validation/cosb/references.bib", self.root)
        (self.root / "metadata.yaml").write_text("bibliography: references.bib\n")
        (self.root / "manuscript.md").write_text(
            "---\ntitle: Layout test\n---\n\n# Introduction\n\n"
            "First paragraph [@example].\n\nSecond paragraph.\n\n"
            "# Methods\n\nAn equation $x+y$.\n\n# References\n\n::: {#refs}\n:::\n"
        )
        self.config = {"journal": "cosb", "reference_doc": REFERENCE}
        self.env = dict(os.environ, PAPERKIT_PANDOC=PANDOC)
        self.env.pop("JOURNAL", None)
        self.write_config()

    def write_config(self):
        (self.root / "paperkit.json").write_text(json.dumps(self.config))

    def command(self, *args, ok=True):
        result = subprocess.run(
            [os.sys.executable, "paperkit.py", *args], cwd=self.root,
            env=self.env, capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def parts(self):
        with ZipFile(self.root / "output/manuscript.docx") as archive:
            return {name: archive.read("word/" + name + ".xml")
                    for name in ("document", "styles")}

    def test_shared_layout_preserves_word_geometry_and_styles(self):
        self.command("build", "--no-appendix")
        parts = self.parts()
        doc = ET.fromstring(parts["document"])
        styles = ET.fromstring(parts["styles"])
        by_name = {s.find("w:name", NS).get(W + "val"): s
                   for s in styles.findall("w:style", NS)}
        normal = by_name["Normal"]
        self.assertEqual(normal.find("w:rPr/w:rFonts", NS).get(W + "ascii"), "Arial")
        self.assertEqual(normal.find("w:rPr/w:sz", NS).get(W + "val"), "22")
        for name in ("Body Text", "First Paragraph"):
            style = by_name[name]
            self.assertEqual(style.find("w:pPr/w:spacing", NS).get(W + "line"), "240")
            self.assertEqual(style.find("w:pPr/w:spacing", NS).get(W + "after"), "120")
            self.assertEqual(style.find("w:pPr/w:ind", NS).get(W + "firstLine"), "0")
            self.assertEqual(style.find("w:pPr/w:jc", NS).get(W + "val"), "both")
        heading = by_name["heading 1"]
        self.assertEqual(heading.find("w:pPr/w:jc", NS).get(W + "val"), "left")
        self.assertIsNotNone(heading.find("w:rPr/w:b", NS))
        self.assertIsNone(heading.find("w:rPr/w:color", NS))
        for name in ("header", "footer"):
            self.assertIsNotNone(by_name[name].find("w:pPr/w:suppressLineNumbers", NS))
        section = doc.find(".//w:sectPr", NS)
        self.assertEqual(section.find("w:pgSz", NS).get(W + "w"), "11906")
        self.assertEqual(section.find("w:pgMar", NS).get(W + "left"), "1800")
        self.assertEqual(section.find("w:lnNumType", NS).get(W + "restart"), "continuous")
        self.assertIn("[1]", "".join(doc.itertext()))
        self.assertTrue(doc.findall(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"))

    def test_changing_csl_preserves_word_layout(self):
        self.command("build", "--no-appendix")
        vancouver = self.parts()
        self.command("build", "--no-appendix", "--csl", "journals/nature/nature.csl")
        nature = self.parts()
        self.assertEqual(vancouver["styles"], nature["styles"])
        self.assertIn("[1]", "".join(ET.fromstring(vancouver["document"]).itertext()))
        self.assertTrue(ET.fromstring(nature["document"]).findall(
            './/w:vertAlign[@w:val="superscript"]', NS))
        self.assertEqual(
            ET.tostring(ET.fromstring(vancouver["document"]).find(".//w:sectPr", NS)),
            ET.tostring(ET.fromstring(nature["document"]).find(".//w:sectPr", NS)),
        )

    def test_cli_precedence_and_doctor_selected_template(self):
        self.config["csl"] = "journals/nature/nature.csl"
        self.write_config()
        output = self.command("build", "--dry-run").stdout
        self.assertIn("--reference-doc=" + REFERENCE, output)
        self.assertIn("--csl=journals/nature/nature.csl", output)
        output = self.command("build", "--dry-run", "--csl", "styles/elsevier-vancouver.csl",
                              "--reference-doc", "journals/cosb/templates/pandoc-reference.docx").stdout
        self.assertIn("--csl=styles/elsevier-vancouver.csl", output)
        self.assertIn("--reference-doc=journals/cosb/templates/pandoc-reference.docx", output)
        output = self.command("doctor").stdout
        self.assertIn(REFERENCE, output)
        self.assertNotIn("does not define every style", output)

    def test_missing_or_external_override_is_rejected(self):
        for args, message in [
            (("--csl", "missing.csl"), "missing configured csl"),
            (("--reference-doc", "missing.docx"), "missing configured reference_doc"),
            (("--reference-doc", "../outside.docx"), "inside the repository"),
        ]:
            with self.subTest(args=args):
                result = self.command("build", "--dry-run", *args, ok=False)
                self.assertIn(message, result.stderr)

    def test_source_templates_contain_no_manuscript_text(self):
        for name in ("main.docx", "pandoc-reference.docx"):
            with ZipFile(ROOT / "templates/manuscript" / name) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
                for part in archive.namelist():
                    if part.startswith(("word/header", "word/footer")) and part.endswith(".xml"):
                        for paragraph in ET.fromstring(archive.read(part)).findall(".//w:p", NS):
                            self.assertIsNotNone(paragraph.find("w:pPr/w:suppressLineNumbers", NS))
            self.assertFalse("".join(t.text or "" for t in document.findall(".//w:t", NS)))


if __name__ == "__main__":
    unittest.main()
