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

Select the journal per build:

```bash
python3 paperkit.py build --journal nature
JOURNAL=nature ./build_docx.sh
```

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
