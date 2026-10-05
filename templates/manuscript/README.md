# Shared manuscript Word layout

This optional layout carries the normalized Word styles supplied from
`scit-itca-paper/shared/templates/pandoc-reference.docx`. It is a reusable draft
layout, not an official template for COSB or another journal. No source manuscript
or publisher instructions are included in either document's body.

- Arial 11 pt body text, single spacing, 6 pt after paragraphs, no first-line indent.
- Justified body and first paragraphs; left-aligned black, bold section headings.
- A4, 1 inch top/bottom and 1.25 inch left/right margins; continuous line numbers.
- Centered title and author styles; editable Word bibliography and caption styles.

Header and footer paragraphs suppress line numbering, so page numbers and empty
header lines do not acquire extra line numbers when rendered in LibreOffice.

`main.docx` is the editable source. `pandoc-reference.docx` is generated from it
with the kit-resolved Pandoc 3.10 and empty Markdown input. To regenerate after
editing the source, run this from the repository root:

```python
from pathlib import Path
import subprocess
import paperkit

pandoc = paperkit.resolve_pandoc(quiet=True)[0]
directory = Path("templates/manuscript")
subprocess.run(
    [pandoc, "--from=markdown", "--reference-doc=" + str(directory / "main.docx"),
     "--output=" + str(directory / "pandoc-reference.docx")],
    input=b"", check=True,
)
```

Select this layout independently of the citation style in manuscript-owned
`paperkit.json`:

```json
{
  "journal": "cosb",
  "reference_doc": "templates/manuscript/pandoc-reference.docx",
  "csl": "styles/elsevier-vancouver.csl"
}
```

`reference_doc` controls the main Word document only. The journal still controls
filters, annotations and its optional appendix template. `csl` controls citation
and bibliography text, including numbering, author lists and punctuation. Changing
the CSL does not replace the Word layout. Bibliography paragraph typography remains
editable in the source Word template.

Run the integration tests and both journal validation suites after changes.
Existing journal fixtures validate journal defaults; the independent-layout
integration tests also exercise this optional template with different CSLs.
