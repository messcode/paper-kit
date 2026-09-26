#!/usr/bin/env python3
"""Make `pandoc-reference.docx` define every Word style Pandoc emits.

Word silently ignores a `w:pStyle` reference whose style does not exist in the
package; the paragraph then falls back to the default style. Nature's
`main.docx` ships `Author-Affiliation` but no style called `Author`, and Pandoc
always emits `pStyle="Author"` for the byline, so the author line loses the
template's byline formatting. The alias table below closes that gap by pointing
each Pandoc style at an existing template style.

The script is idempotent and template-preserving:

* it only adds styles that are missing, never modifies or removes existing ones;
* it edits `word/styles.xml` with a targeted string insertion, so every other
  part of the package stays byte-identical;
* it never regenerates the reference document from `main.docx`, so any manual
  style tuning already present in the reference document is preserved.

Usage:

    python3 journals/add_missing_styles.py --journal nature
    python3 journals/add_missing_styles.py --journal nature --check
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

# Pandoc style name -> template style whose formatting it should inherit.
# Extend this table if a manuscript needs another Pandoc-internal style
# (for example "Compact" for table cells).
ALIASES = {
    "Author": "Author-Affiliation",
}

STYLES_MEMBER = "word/styles.xml"


class Failure(Exception):
    """A user-facing error."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def style_inventory(xml: str):
    """Return (set of styleIds, set of style names) present in styles.xml."""
    ids = set(re.findall(r'w:styleId="([^"]+)"', xml))
    names = set()
    for block in re.findall(r"<w:style\b.*?</w:style>", xml, re.S):
        match = re.search(r'<w:name w:val="([^"]*)"', block)
        if match:
            names.add(match.group(1))
    return ids, names


def resolve_based_on(target: str, ids, names):
    """Accept either a styleId or a style name for the parent style."""
    if target in ids:
        return target
    if target in names:
        return target
    raise Failure(
        "the template does not define a style named %r, so %r cannot inherit "
        "from it; available candidates: %s"
        % (target, target, ", ".join(sorted(names))[:400])
    )


def build_style_xml(style_id: str, based_on: str, indent: str) -> str:
    pad = " " * len(indent)
    return (
        '%s<w:style w:type="paragraph" w:customStyle="1" w:styleId="%s">\n'
        '%s  <w:name w:val="%s"/>\n'
        '%s  <w:basedOn w:val="%s"/>\n'
        '%s  <w:qFormat/>\n'
        "%s</w:style>\n"
        % (indent, style_id, pad, style_id, pad, based_on, pad, indent)
    )


def patch_styles_xml(xml: str) -> tuple:
    """Return (new xml, list of added style ids)."""
    ids, names = style_inventory(xml)
    added = []
    blocks = []

    for style_id, parent in sorted(ALIASES.items()):
        if style_id in ids or style_id in names:
            continue
        based_on = resolve_based_on(parent, ids, names)
        blocks.append(build_style_xml(style_id, based_on, "  "))
        added.append("%s (inherits %s)" % (style_id, based_on))

    if not blocks:
        return xml, []

    marker = "</w:styles>"
    if marker not in xml:
        raise Failure("word/styles.xml has no </w:styles> closing tag")
    return xml.replace(marker, "".join(blocks) + marker, 1), added


def read_member(docx: Path, member: str) -> str:
    try:
        with zipfile.ZipFile(str(docx)) as archive:
            return archive.read(member).decode("utf-8")
    except KeyError:
        raise Failure("%s has no %s" % (docx.name, member))
    except zipfile.BadZipFile:
        raise Failure("%s is not a valid DOCX package" % docx)


def write_patched(docx: Path, new_styles: str) -> None:
    """Rewrite the package with one member replaced, keeping the rest as-is."""
    temporary = docx.with_suffix(".docx.patched")
    with zipfile.ZipFile(str(docx)) as source:
        with zipfile.ZipFile(str(temporary), "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                if item.filename == STYLES_MEMBER:
                    target.writestr(item, new_styles.encode("utf-8"))
                else:
                    target.writestr(item, source.read(item.filename))
    temporary.replace(docx)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", default="nature", help="journal asset set under journals/ (default: nature)")
    parser.add_argument("--check", action="store_true", help="report missing styles without writing")
    parser.add_argument(
        "--reference",
        help="path to pandoc-reference.docx (default: journals/<journal>/templates/pandoc-reference.docx)",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    reference = (
        Path(args.reference)
        if args.reference
        else root / "journals" / args.journal / "templates" / "pandoc-reference.docx"
    )
    if not reference.is_file():
        raise Failure("missing reference document: %s" % reference)

    xml = read_member(reference, STYLES_MEMBER)
    patched, added = patch_styles_xml(xml)

    if not added:
        print("%s already defines every Pandoc style." % reference.name)
        return 0

    for description in added:
        print("  %s %s" % ("missing:" if args.check else "+", description))

    if args.check:
        print("")
        print("  run without --check to add them:")
        print("    python3 journals/add_missing_styles.py --journal %s" % args.journal)
        return 1

    write_patched(reference, patched)
    print("Updated %s" % reference)
    print("  rebuild the manuscript and refresh the smoke-test baseline:")
    print("    python3 paperkit.py build && python3 paperkit.py validate --update")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print("error: %s" % error, file=sys.stderr)
        sys.exit(2)
