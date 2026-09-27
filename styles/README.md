# Shared citation styles

`elsevier-vancouver.csl` is the unmodified CSL project style **Elsevier -
NLM/Vancouver (citation-sequence)**. It is suitable for some Elsevier journals,
not a universal publisher-wide style. COSB selects it through its profile.

- Source: https://github.com/citation-style-language/styles/blob/master/elsevier-vancouver.csl
- Retrieved: 2026-09-27
- Upstream Git blob: `c0b242a13fcf2803ab03fdd99b9b0c984329f10e`
- Author: Richard Karnesky; attribution is retained in the CSL header.
- License: Creative Commons Attribution-ShareAlike 3.0,
  https://creativecommons.org/licenses/by-sa/3.0/

This style uses bracketed citation numbers, first-citation order, first six
names plus et al. for more than six authors, shortened page ranges, and DOI URLs.
Typographic page-range dashes can render as en dashes. Journal abbreviations
must be supplied correctly in bibliography metadata; CSL cannot infer every
journal's official abbreviation. Use separate initials (e.g. `J. A. J.`) in
BibTeX author given names rather than an ambiguous single token `JAJ`.

When updating the upstream file, record the new blob and run both journal
validation suites plus the integration tests. Do not silently refresh fixtures.
