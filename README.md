# paper-kit

Write a manuscript in Markdown, export it to DOCX with Pandoc. One shared kit,
one git repository per manuscript.

Works on Linux, macOS and Windows with nothing but Python 3.8+ and git.

## Quick start

```bash
# one-time: install the pinned Pandoc 3.10 into the per-user cache
python3 paperkit.py setup

# check everything
python3 paperkit.py doctor

# rebuild the export smoke tests and compare with the committed fixtures
python3 paperkit.py validate

# export output/manuscript.docx (and output/appendix.docx when configured)
python3 paperkit.py build
```

On Windows use `py -3` (or `python`) instead of `python3`, and
`build_docx.cmd` instead of `build_docx.sh`.

## Starting a new manuscript

```bash
cd ~/projects/manuscripts
git clone git@github.com:<owner>/paper-kit.git my-new-paper
cd my-new-paper
git remote rename origin kit                  # keep the kit available as upstream
python3 paperkit.py new                       # write the manuscript skeleton
python3 paperkit.py setup
python3 paperkit.py build

git add -A && git commit -m "chore: start my-new-paper"
gh repo create my-new-paper --private --source=. --push
```

Renaming `origin` to `kit` matters: the new repository must push to its **own**
remote, and `kit` stays around so later improvements can be merged in:

```bash
git fetch kit && git merge kit/main
```

### Start a standalone LaTeX supplement

The [Nature-style supplementary information template](journals/nature/templates/appendix.tex)
builds a standalone PDF. To include it when initializing a new manuscript,
run this from the root of the new clone:

```bash
python3 paperkit.py new --latex-appendix
```

This copies the template to `appendix.tex` at the manuscript root. An existing
`appendix.tex` is preserved even with `--force`. Without `--latex-appendix`,
`new` skips the LaTeX template. Edit the root-level copy to fill in the
manuscript title, authors and affiliations.
Uncomment the note, figure, table and bibliography examples as needed.

Use a TeX installation with XeLaTeX, `latexmk` and the packages listed in the
template preamble. XeLaTeX must be able to find **TeX Gyre Heros** for body
text and **TeX Gyre Termes Math** for mathematics. The blank template can be
compiled before adding any figures or bibliography. From the manuscript root, run

```bash
latexmk -xelatex appendix.tex
```

This writes `appendix.pdf` beside the source. After editing, rerun the same
command. `latexmk` takes care of the extra passes for the lists and cross-references.

## Repository layout

```
.
├── AGENTS.md                     instructions for AI agents and collaborators
├── paperkit.py                   single entry point: setup / doctor / new / build
├── build_docx.sh, build_docx.cmd thin wrappers
├── metadata.yaml                 journal-agnostic Pandoc metadata
├── journals/<name>/              citation style + Word templates per journal
├── validation/                   export pipeline smoke tests
├── manuscript.md, appendix.md    the manuscript
├── references.bib                Zotero + Better BibTeX export
├── figures/, tables/             assets referenced from the Markdown
├── materials/                   local PDFs, prior drafts, private notes; git-ignored
├── notes/                       versioned literature summaries and writing plans
├── submissions/                  frozen DOCX snapshots
└── output/                       generated, git-ignored
```

## Journal templates

`journals/<name>/templates/pandoc-reference.docx` supplies all Word styling
(page setup, margins, heading and caption styles). Put the publisher's own
document at `journals/<name>/templates/main.docx`, then derive the reference copy
from it. Body text in the template is not merged into the export.

Add `journals/<name>/templates/appendix-reference.docx` to enable the appendix
export; `paperkit.py doctor` warns while it is missing.

Pandoc refers to Word styles by *its own* names (`Author`, `FirstParagraph`,
`Compact`), and Word silently drops a reference the package does not define.
`journals/add_missing_styles.py` aliases those names onto the template's own
styles, so e.g. the byline picks up the journal's author formatting:

```bash
python3 journals/add_missing_styles.py --journal nature --check
python3 journals/add_missing_styles.py --journal nature
python3 paperkit.py validate --update
```

Select the journal per build:

```bash
python3 paperkit.py build --journal nature
JOURNAL=nature ./build_docx.sh
```

### Choose Word layout and citation style independently

The optional shared layout at `templates/manuscript/pandoc-reference.docx` uses
Arial body text, black section headings, A4 pages and continuous line numbers.
It is a manuscript drafting layout, not an official journal submission template.
See `templates/manuscript/README.md` for its source and regeneration instructions.

Select it in manuscript-owned `paperkit.json` without changing the journal:

```json
{
  "journal": "cosb",
  "reference_doc": "templates/manuscript/pandoc-reference.docx",
  "csl": "styles/elsevier-vancouver.csl"
}
```

Each override is optional. With neither set, journal defaults are unchanged.
`reference_doc` controls the main DOCX layout; `csl` controls in-text citations and
bibliography formatting. Both paths must stay inside the repository. They do not
change journal filters, annotations or the optional appendix template.
CLI options override the corresponding configuration values:

```sh
python3 paperkit.py build --reference-doc templates/manuscript/pandoc-reference.docx
python3 paperkit.py build --csl journals/nature/nature.csl
python3 paperkit.py doctor
```

`doctor` reports and checks the selected assets. `validate` continues to test each
journal's default fixtures, independently of these manuscript-level overrides.

## Validation

`validation/` holds small Markdown sources with committed DOCX fixtures. They
capture the export output for a fixed Pandoc version and template, so any change
to either is visible as a precise part-level diff:

```bash
python3 paperkit.py validate              # rebuild and compare
python3 paperkit.py validate --verbose    # also print the pandoc commands
python3 paperkit.py validate --update     # refresh the fixtures after a deliberate change
```

Compared parts: `word/document.xml`, `word/styles.xml`, `word/numbering.xml`.
Package metadata is ignored because it embeds build timestamps. A fixture named
`x-default.docx` is built with Pandoc's own reference document and acts as the
baseline showing what the journal template changes.

## References

Export the Zotero library with Better BibTeX into `references.bib` and cite in
Markdown as `[@Stuart2019]`. The CSL file at `journals/<name>/<name>.csl` controls
in-text citation and bibliography formatting. Keep exactly one bibliography per
manuscript.

## Reproducibility

Record the toolchain in `REPRODUCIBILITY.md`:

- the `paper-kit` commit (`git log kit/main -1 --format=%H`)
- the Pandoc version (`python3 paperkit.py doctor`)

Freeze a submission by tagging the commit and archiving the DOCX:

```bash
git tag -a v1-nature-submission -m "submitted to Nature"
mkdir -p submissions/v1-nature-submission
cp output/manuscript.docx submissions/v1-nature-submission/
```

## Pandoc

Pandoc is installed once per user and shared by every manuscript on the machine
(`~/.cache/paperkit`, `~/Library/Caches/paperkit`, or `%LOCALAPPDATA%\paperkit`),
verified against a pinned SHA-256. It is deliberately not committed: the
unpacked binary is 160-230 MB. See `AGENTS.md` for the full resolution order.

## Writing materials and notes

`python3 paperkit.py new` creates these folders for each new manuscript:

```text
materials/                 # local only; ignored by Git
  previous-drafts/         # older manuscripts and annotated Word files
  papers/                  # reference PDFs
  incoming/                # material awaiting organisation
  private-notes/           # notes that should not be published
notes/                     # intended for Git version control
  literature/              # your literature summaries, named by citation key
  outline.md               # review question, scope, and argument
  search-log.md            # databases, dates, queries, and selection criteria
```

For an existing manuscript, merge the kit update, then run:

```bash
git fetch kit
git merge kit/main
python3 paperkit.py materials
```

The `materials` command is safe to repeat: it only adds missing directories and
starter notes, never overwrites manuscript files or existing notes, and requires
no Pandoc installation. Run it again after cloning a manuscript because ignored
materials do not travel with Git. `new --force` also preserves existing notes.

Keep your own summaries and evidence synthesis in `notes/` when appropriate for
sharing with collaborators. Use citation keys and DOI/URL links to identify
sources; `references.bib` remains the single manuscript bibliography. Put final
publication figures and tables in `figures/` and `tables/`.

Ignoring files is not a backup: back up `materials/` separately. Ignore rules do
not remove files already tracked by Git; review `git ls-files materials` before
adding sensitive sources, and do not force-add this directory.

## Contributing kit improvements

Fix shared build bugs, journal support, and reusable workflow features in a
branch of `paper-kit`; validate the change and merge it through a pull request.
An issue is useful for reporting or discussing a problem, but is not required
before a small fix. Keep manuscript prose and source materials out of the kit.
Then merge `kit/main` into each manuscript and update its `REPRODUCIBILITY.md`
kit commit. Do not push a manuscript branch back to the kit.

## Shared citation styles and COSB

The COSB profile reuses the established Elsevier Vancouver CSL in `styles/`;
it does not duplicate that style under the journal directory. See
[journals/cosb/README.md](journals/cosb/README.md) for the manuscript-owned
`paperkit.json` selection and `reference-annotations.json` format. It supplies
bracketed body citations and bibliography-only interest stars and descriptions.
The COSB Word reference is Pandoc's generic single-column template, not an
official publisher template.

```bash
python3 paperkit.py build --journal cosb --no-appendix
python3 paperkit.py doctor --journal cosb
python3 paperkit.py validate --journal cosb
python3 paperkit.py validate --journal nature
python3 -m unittest discover -s tests -v
```

CLI journal selection works before or after the subcommand. Resolution is
`--journal`, then the `JOURNAL` environment variable, then `paperkit.json`, then
Nature. Both build wrappers use that same resolution. A manuscript can select
COSB without changing kit-owned source code.

## Body word count

```sh
python3 paperkit.py wordcount
python3 paperkit.py wordcount --limit 2000 --json
```

Set `"word_limit": 2000` in manuscript-owned `paperkit.json` when the invitation
requires it. No journal-wide limit is assumed. `--limit` overrides that value;
`--source` selects another Markdown file. Exit status is 0 within the limit
(or without a configured limit), 1 over it, and 2 for invalid input.

Counting uses Pandoc's Markdown AST before citeproc. Body section headings,
table captions/cells, box text, and footnotes count conservatively. YAML title,
author/date/keywords, abstract, reference sections (including annotations), and
figure captions are excluded. Generated bibliography and external annotation
files are never counted or loaded, so the reference subtotal measures only
reference prose present in the source. Appendix files are not read implicitly.

Recognized section headings are `Abstract`, `References`, `References and
recommended reading`, `Figure legends`, `Figure captions`, and `Keywords`
(case insensitive). An excluded section ends at the next same/higher-level
heading. Use consistent heading levels; arbitrary headings are body text.
Standalone Pandoc figures supply their caption automatically. For separate
legends or nonstandard section labels, classify a fenced Div explicitly:

```markdown
::: {wordcount="figure-legends"}
Figure 1. The figure legend goes here.
:::
```

Other categories are `abstract`, `references`, `front-matter`, and `body`.
Only use exclusions justified by the invitation. Plain paragraphs labelled
“Figure 1” are not guessed to be captions; mark them explicitly. Use Pandoc
citations (`[@Key]`): citation identifiers/numbers are excluded while citation
prefix/suffix prose counts. Manually typed `[1]` cannot be distinguished from
ordinary numbers and counts. Numbers and hyphenated/contraction words each
count as one; math expressions count as one with a review warning. Raw markup
(except comments), code, image alt text, TODOs and CJK prose trigger review
warnings where relevant. This is an English prose estimate, not a claim to
reproduce Microsoft Word or an unspecified publisher tokenizer exactly.
