# AGENTS.md — paperkit

This file is the authoritative instruction set for AI agents (and humans) working
in any repository that descends from `paper-kit`. Read it fully before acting.

Upstream sections of this file are maintained by `paper-kit`. Manuscript-specific
instructions go in the `## Manuscript-specific notes` section at the end, which
upstream never touches.

---

## 1. What this repository is

A manuscript is written in Markdown and exported to DOCX with Pandoc. The DOCX
styling (page setup, heading styles, figure/table caption styles) is inherited
from a journal-supplied Word document through Pandoc's `--reference-doc`
mechanism. Existing body text in that template is **not** merged into the export.

There are two kinds of repositories in this system:

| Repository | Owns | Never contains |
|---|---|---|
| `paper-kit` (one, shared) | `paperkit.py`, `journals/`, `validation/`, this file | any manuscript content |
| `<paper>-paper` (one per manuscript) | `manuscript.md`, `appendix.md`, `references.bib`, `figures/`, `tables/` | edits to kit-owned files |

A manuscript repository starts as a clone of `paper-kit` (so they share git
history), then gets **its own `origin` remote**. The kit clone is kept as a
second remote named `kit` so improvements can be merged in later.

## 2. Repository layout

```
manuscript root
├── AGENTS.md                  this file (kit-managed; see section 9)
├── README.md                  quick start (kit-managed)
├── paperkit.py                the only build entry point (kit-managed)
├── build_docx.sh / .cmd       thin wrappers for Unix / Windows (kit-managed)
├── .gitattributes             line-ending and binary rules (kit-managed)
├── .gitignore                 (kit-managed)
├── metadata.yaml              journal-agnostic Pandoc metadata (paper-owned)
├── journals/<name>/           journal asset set (kit-managed)
│   ├── add_missing_styles.py  aliases Pandoc style names onto template styles
│   ├── <name>.csl             CSL citation style
│   └── templates/
│       ├── main.docx               the publisher's Word template
│       ├── pandoc-reference.docx   styles extracted from main.docx
│       └── appendix-reference.docx optional; enables appendix export
├── validation/                smoke tests for the export pipeline (kit-managed)
├── manuscript.md              main text (paper-owned)
├── appendix.md                supplementary material (paper-owned)
├── references.bib             Zotero + Better BibTeX export (paper-owned)
├── figures/                   final figure files referenced by the Markdown
├── tables/                    generated table fragments, if any
├── materials/                local source material and private notes; git-ignored
├── notes/                    versioned literature summaries and writing plans
├── submissions/               frozen DOCX snapshots, one folder per submission
└── output/                    generated DOCX; git-ignored, disposable
```

## 3. Prerequisites

- Python 3.8 or newer (`python3` on Linux/macOS, `py -3` or `python` on Windows)
- git
- Nothing else. Pandoc is installed by `paperkit.py setup`; no virtualenv, no
  admin rights, no package manager required.

## 4. Commands

Run every command from the manuscript root.

```bash
python3 paperkit.py setup       # install the pinned Pandoc 3.10 into the user cache
python3 paperkit.py doctor      # verify environment, journal assets, git hygiene
python3 paperkit.py validate    # rebuild the smoke tests and compare with the fixtures
python3 paperkit.py new         # write the manuscript skeleton into a fresh clone
python3 paperkit.py materials   # add materials/ and notes/ without overwriting files
python3 paperkit.py build       # export manuscript.md (and appendix.md) to output/
```

Windows: substitute `py -3` or `python` for `python3`.

Useful flags:

```bash
python3 paperkit.py build --dry-run           # print the exact pandoc invocation
python3 paperkit.py build --journal nature    # select the journal asset set
python3 paperkit.py build --no-appendix       # skip appendix.md
python3 paperkit.py build --pandoc /path/to/pandoc
python3 paperkit.py validate --update         # refresh the smoke-test baseline
python3 paperkit.py doctor                    # run this first when anything fails
python3 journals/add_missing_styles.py --journal nature --check
```

`build_docx.sh` / `build_docx.cmd` are conveniences that forward to
`paperkit.py build`; the Python script is the single source of truth, so put any
new logic there and never in the wrappers.

## 5. Pandoc

Pandoc 3.10 is pinned and installed per user into a shared cache, so one copy
serves every manuscript on the machine:

| Platform | Cache location |
|---|---|
| Linux | `$XDG_CACHE_HOME/paperkit` or `~/.cache/paperkit` |
| macOS | `~/Library/Caches/paperkit` |
| Windows | `%LOCALAPPDATA%\paperkit` |

The download is verified against a pinned SHA-256 (`PANDOC_ASSETS` in
`paperkit.py`) before extraction. Pandoc is resolved in this order:

1. `--pandoc <path>`
2. the `PAPERKIT_PANDOC` environment variable
3. the per-user cache
4. `pandoc` on `PATH`, if it reports 3.x or newer

The binary is **never** vendored into a repository: it is 160-230 MB
uncompressed. Any `tools/bin/pandoc` you find is legacy and should be deleted.

Pandoc version affects DOCX output, so record it in `REPRODUCIBILITY.md`. After
changing `PANDOC_VERSION`, or after replacing anything under
`journals/<name>/templates/`, run `python3 paperkit.py validate`. It rebuilds
`validation/*.md` and compares `word/document.xml`, `word/styles.xml` and
`word/numbering.xml` against the committed fixtures, printing a per-part diff.
Only refresh the baseline with `validate --update` once you have confirmed that
the new output is the intended one.

## 6. Starting a new manuscript

```bash
cd ~/projects/manuscripts
git clone git@github.com:<owner>/paper-kit.git <slug>-paper
cd <slug>-paper
git remote rename origin kit                       # keep the kit as upstream
python3 paperkit.py new --kit <owner>/paper-kit@<sha>
python3 paperkit.py setup
python3 paperkit.py build
git add -A && git commit -m "chore: start <slug> manuscript"
gh repo create <slug>-paper --private --source=. --push   # its own origin
```

## 7. Pulling kit improvements into an existing manuscript

```bash
git fetch kit && git merge kit/main
```

This merges cleanly as long as kit-owned files were not edited locally. If a
merge conflicts inside a kit-owned file, resolve it in favour of the kit version
(`git checkout --theirs <file>` for the conflicting path) — never fork the kit
logic into a single manuscript.

## 8. Hard rules

1. Never commit `output/`. It is generated and git-ignored; verify with
   `git status --ignored`.
2. Never commit a Pandoc binary. `paperkit.py setup` handles it.
3. Never edit `journals/<name>/templates/pandoc-reference.docx` by hand. It is
   derived from `main.docx`; if `main.docx` changes, regenerate the reference
   copy rather than patching styles in it. Verify with
   `python3 paperkit.py validate` afterwards.
4. Never add manuscript content (prose, bibliography, figures) to `paper-kit`.
5. Keep exactly one bibliography per manuscript (`references.bib`). Zotero with
   Better BibTeX is the single source of truth; export a per-manuscript subset.
6. Put figure *generation* code in the analysis repository, not here. Only the
   final rendered figure files belong in `figures/`. The analysis repository is
   optional: plenty of manuscripts have no code behind them.
7. If the manuscript does depend on an analysis repository, record its URL and
   the frozen commit SHA in the *optional* Code Snapshot section of
   `REPRODUCIBILITY.md`. Never require a specific local path there.
8. Tag submission freezes (`git tag -a v1-<journal>-submission`) and copy the
   submitted DOCX into `submissions/<tag>/`; do not rely on `output/`.

## 9. Cross-platform notes

- All text files are normalised to LF via `.gitattributes`; `.cmd` files stay
  CRLF. Do not commit files with mixed line endings.
- Use `pathlib`-style relative paths in scripts. Commands are constructed as
  argument lists, never as shell strings, so paths containing spaces work
  everywhere.
- On macOS the pinned download is not quarantined because it is fetched by
  Python rather than a browser. If you copy a Pandoc binary in manually and it is
  blocked, clear the flag with
  `xattr -d -r com.apple.quarantine <path>`.
- On Windows, run from PowerShell, cmd.exe or Git Bash. `build_docx.cmd` covers
  the first two; `build_docx.sh` works under Git Bash.
- Do not rely on `make`, `bash`-only utilities, `sed` or symlinks in anything the
  build depends on.

## 10. Style-specific setup

Pandoc emits `w:pStyle` values that are *style names from its own default
reference document* (`Title`, `Author`, `FirstParagraph`, `Compact`, ...). Word
silently ignores a reference to a style the package does not define and falls
back to the default paragraph style. A publisher template is unlikely to use
Pandoc's names, so byline, author-affiliation or table-cell paragraphs can lose
their formatting without any error being raised.

Fix that with the alias table rather than by hand-editing the DOCX:

```bash
python3 journals/add_missing_styles.py --journal nature --check   # report only
python3 journals/add_missing_styles.py --journal nature           # add aliases
python3 paperkit.py validate --update                             # new baseline
```

The script only *adds* styles that are missing and rewrites nothing else in the
package, so existing template tuning is preserved. Extend `ALIASES` in that
script when a manuscript needs another Pandoc-internal style. `paperkit.py
doctor` runs the `--check` form automatically.

If a manuscript needs a style that exists under a different name, the
`::: {custom-style="Template Style Name"}` div is the direct way to apply it:

```markdown
::: {custom-style="Author-Affiliation"}
Alice First, Bob Second
:::
```

## 11. Markdown gotchas

- Inline math is `$I(Y; Z)$`. Wrapping it in backticks (`` `$I(Y; Z)$` ``) makes
  it a code span, and it will appear literally in the DOCX instead of becoming a
  Word equation. This is the most common reason “the formula did not convert”.
- `# X` maps to Word `Heading 1`, `## X` to `Heading 2`, `### X` to
  `Heading 3`. Journal templates style those three levels very differently, so
  keep the heading depth of the manuscript stable when comparing revisions.
- A style that the journal template does not define (commonly `Author`,
  `FirstParagraph` and `Compact`) still appears in the exported DOCX but Word
  falls back to `Normal`. `python3 paperkit.py doctor` does not flag this;
  check it with `python3 paperkit.py validate` or by inspecting `styles.xml`.

## 12. Writing materials

- `materials/` holds previous drafts, reference PDFs, incoming material, and
  private notes. It is git-ignored and needs a separate backup. Never force-add
  it. Ignore rules do not untrack files already committed.
- `notes/` holds manuscript-owned literature summaries, outlines, and search
  records intended for version control. Use citation keys to connect notes to
  the single `references.bib` bibliography.
- `new` creates both folder structures. Existing manuscripts should run
  `python3 paperkit.py materials` after merging the kit update. This command
  preserves existing files and does not require Pandoc.
- Keep all manuscript-specific source material and notes out of `paper-kit`.


## 13. Journal profiles and annotated references

- Shared CSL files live under `styles/`; journal `profile.json` files select
  repository-relative CSL/filter paths and isolated validation folders.
- Manuscript-owned `paperkit.json` sets the default journal; `--journal` and
  `JOURNAL` can override it. Nature remains the fallback for existing projects.
- COSB uses the shared Elsevier Vancouver style and Pandoc's generic single-column
  reference DOCX, not an official publisher template. Do not claim full submission
  compliance merely because the export succeeded.
- Manuscript-owned `reference-annotations.json` holds actual citation-key-based
  stars, plain-text annotations, confirmed dates, and the review period. Never
  place a manuscript's annotations or bibliography in this shared kit.
- COSB annotations are inserted after citeproc and only in the bibliography.
  Validate dates and flag insufficient/unused annotations; never invent content.
- When changing citation logic, run `python3 -m unittest discover -s tests -v`,
  `python3 paperkit.py validate --journal cosb`, and the Nature validation suite.
  Inspect intentional output changes before updating fixtures.
- Follow each manuscript's invitation where it conflicts with general guidance.

## 14. Word-count checks

- `python3 paperkit.py wordcount` parses the source with Pandoc, before citeproc.
- Keep invitation-specific `word_limit` in manuscript-owned `paperkit.json`.
- Exclude only documented categories; table/box prose and section headings
  count conservatively. Mark standalone legends with `wordcount="figure-legends"`
  Divs and use standard headings as documented in README.md.
- Report warnings and draft placeholders alongside totals; a passing count is
  not submission approval. Do not silently discard unrecognized body sections.
- Run the word-count integration tests when changing traversal or tokenization.

## Manuscript-specific notes

<!-- Append instructions that apply only to this manuscript below this line.
     Upstream never edits this section. -->
