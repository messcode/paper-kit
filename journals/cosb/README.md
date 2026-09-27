# Current Opinion in Systems Biology

This profile reuses `styles/elsevier-vancouver.csl`. The bibliography-only Lua
filter runs after citeproc and adds the recommended-reading heading, legend,
and key-associated interest markers/annotations. Body citations remain plain
bracketed numbers. The feature does not invent annotations or choose papers.

## Select the profile

Create manuscript-owned `paperkit.json` in the manuscript root:

```json
{"journal": "cosb"}
```

Then run `python3 paperkit.py build --no-appendix` or `./build_docx.sh`.
Selection order is explicit `--journal`, `JOURNAL` environment variable,
`paperkit.json`, then `nature`. The CLI flag works before or after the command.
Use `python3 paperkit.py validate --journal cosb` for this profile's fixtures;
Nature's committed fixtures remain separate.

## Word layout

`templates/pandoc-reference.docx` is the standard single-column reference
package from pinned Pandoc 3.10, **not a publisher-supplied or officially
approved COSB template**. It avoids applying Nature typography to this journal.
Regenerate from the pinned binary, without hand-editing the package:

```sh
pandoc --print-default-data-file reference.docx -o journals/cosb/templates/pandoc-reference.docx
```

No appendix template is shipped; the existing build behavior skips appendices
and doctor warns. Keep editable table/equation sources and review all actual
submission formatting against the invitation and author guide.

## Manuscript-owned annotations

Create `reference-annotations.json`; an empty draft starts with:

```json
{"reference-annotations": {}}
```

Once the review window and publication dates have been confirmed, use this
schema (the key and annotation below are illustrative placeholders):

```json
{
  "review-period-start": "2024-09-27",
  "review-period-end": "2026-09-27",
  "reference-annotations": {
    "CitationKey": {
      "interest": "*",
      "published": "2025-02-01",
      "text": "Describe the verified major finding and why it matters."
    }
  }
}
```

`interest` is `*` or `**`. `text` is plain prose. Dates must be ISO YYYY-MM-DD;
nonempty annotations require an explicit period no longer than two calendar
years, and each publication date must be inside it. The tool validates the
supplied dates, not their truth or the editor's choice of publication version.
Do not use today's date or a guessed period automatically. Readers of the
manuscript, not the software, judge scientific importance.

Annotations follow citation keys when numbers change, and appear only under
the matching bibliography entries. Entries not cited in the current document
produce warnings (useful for a shared main/appendix annotation bank); check such
warnings for misspelled keys. A draft with fewer than ceil(reference count/10)
annotations warns but still builds. Final submission requires author review.
No hard word or reference-count limit is imposed: the specific invitation is
authoritative where it differs from general website guidance.

`references.bib`, `paperkit.json`, and `reference-annotations.json` are owned by
each manuscript; actual paper selections and annotations never belong in the
shared kit. Fixture data under `validation/cosb/` is synthetic and is not
scientific evidence.
