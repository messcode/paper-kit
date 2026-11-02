#!/usr/bin/env python3
"""paperkit - cross-platform manuscript build helper (Markdown + Pandoc -> DOCX).

Single entry point for every manuscript repository derived from this kit:

    python3 paperkit.py setup     # install the pinned Pandoc into the user cache
    python3 paperkit.py doctor    # verify the local environment and assets
    python3 paperkit.py new       # turn a fresh clone into a new manuscript
    python3 paperkit.py build     # export manuscript.md / appendix.md to DOCX

Only the Python standard library is used, so no virtualenv is required.
Tested on Linux, macOS and Windows with Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

try:
    from pathlib import Path
except ImportError:  # pragma: no cover - Python 3.5 or older
    sys.exit("paperkit requires Python 3.8 or newer")

# --------------------------------------------------------------------------
# Pinned Pandoc release
# --------------------------------------------------------------------------

PANDOC_VERSION = "3.10"
MIN_PANDOC = (3, 0)
RELEASE_URL = (
    "https://github.com/jgm/pandoc/releases/download/{version}/{asset}"
)

# (sys.platform family, normalised arch) -> (asset name, sha256, archive kind,
# path of the executable inside the archive)
PANDOC_ASSETS = {
    ("linux", "x86_64"): (
        "pandoc-{v}-linux-amd64.tar.gz",
        "e0f8af62d0f267d22baa5bcefe6d5dda3a097ccc60de794b759fe03159923244",
        "tar.gz",
        "pandoc-{v}/bin/pandoc",
    ),
    ("linux", "arm64"): (
        "pandoc-{v}-linux-arm64.tar.gz",
        "55413dfb0c1aec861641fe858f1f73e84848f3db497b1c0c02e62887ea76f4a4",
        "tar.gz",
        "pandoc-{v}/bin/pandoc",
    ),
    ("darwin", "x86_64"): (
        "pandoc-{v}-x86_64-macOS.zip",
        "6334f4d9af7c9e37e761dfad56fa5507685f6d29724ebf31c4be6d5c654a3161",
        "zip",
        "pandoc-{v}-x86_64/bin/pandoc",
    ),
    ("darwin", "arm64"): (
        "pandoc-{v}-arm64-macOS.zip",
        "d9cad01d96ae774a0dc8c8c45bb1ad3e4c5ff2cc2e24f45958f5f9b7974aee34",
        "zip",
        "pandoc-{v}-arm64/bin/pandoc",
    ),
    ("windows", "x86_64"): (
        "pandoc-{v}-windows-x86_64.zip",
        "bb808d00fd58762299d64582a9b4c3e4b106cd929e62c5f19bcdcb496f1e54ae",
        "zip",
        "pandoc-{v}/pandoc.exe",
    ),
}


class Failure(Exception):
    """A user-facing error; printed without a traceback."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def is_windows() -> bool:
    return os.name == "nt"


def exe_suffix() -> str:
    return ".exe" if is_windows() else ""


def platform_family() -> str:
    if is_windows():
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    raise Failure("unsupported operating system: %s" % sys.platform)


def normalise_arch() -> str:
    machine = (os.environ.get("PAPERKIT_ARCH") or _machine()).lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    raise Failure(
        "unsupported CPU architecture: %s"
        % machine
    )


def _machine() -> str:
    # platform.machine() is reliable on all three platforms, including
    # Windows ARM64 running x64 Python through emulation.
    import platform as _p

    return _p.machine()


def cache_root() -> Path:
    """Per-user cache directory, following each platform's convention."""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "paperkit"


def cached_pandoc() -> Path:
    return cache_root() / "pandoc" / PANDOC_VERSION / ("pandoc" + exe_suffix())


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text with LF endings (Path.write_text gained `newline` in 3.10)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, cwd=None, capture=False):
    if capture:
        return subprocess.run(
            command,
            cwd=None if cwd is None else str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    return subprocess.run(command, cwd=None if cwd is None else str(cwd))


def pandoc_version(executable: str):
    """Return (major, minor) for a Pandoc executable, or None."""
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout.startswith("pandoc "):
        return None
    raw = result.stdout.splitlines()[0].split()[1]
    parts = []
    for token in raw.split(".")[:2]:
        digits = "".join(c for c in token if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts)


def resolve_pandoc(explicit=None, quiet=False):
    """Find a usable Pandoc: explicit flag, env var, cache, then PATH."""
    candidates = []
    if explicit:
        candidates.append(("--pandoc", str(explicit)))
    env_value = os.environ.get("PAPERKIT_PANDOC")
    if env_value:
        candidates.append(("PAPERKIT_PANDOC", env_value))
    candidates.append(("cache", str(cached_pandoc())))
    found = shutil.which("pandoc")
    if found:
        candidates.append(("PATH", found))

    for origin, spec in candidates:
        path = Path(spec)
        if not path.is_file():
            which = shutil.which(spec)
            if not which:
                continue
            path = Path(which)
        version = pandoc_version(str(path))
        if version is None:
            if not quiet:
                print("  ! ignoring unusable Pandoc from %s: %s" % (origin, path))
            continue
        if version < MIN_PANDOC:
            if not quiet:
                print(
                    "  ! ignoring Pandoc %d.%d from %s (need %d.%d or newer, "
                    "--citeproc is unavailable in 2.x)"
                    % (version[0], version[1], origin, MIN_PANDOC[0], MIN_PANDOC[1])
                )
            continue
        return str(path), version, origin

    if explicit:
        raise Failure("Pandoc not found at: %s" % explicit)
    return None, None, None


def describe_asset():
    family = platform_family()
    arch = normalise_arch()
    try:
        template, digest, kind, member = PANDOC_ASSETS[(family, arch)]
    except KeyError:
        supported = ", ".join("%s/%s" % key for key in sorted(PANDOC_ASSETS))
        raise Failure(
            "no pinned Pandoc build for %s/%s\n  supported combinations: %s\n"
            "  you can also install Pandoc yourself and put it on PATH, or point "
            "PAPERKIT_PANDOC at an existing binary." % (family, arch, supported)
        )
    asset = template.format(v=PANDOC_VERSION)
    return asset, digest, kind, member.format(v=PANDOC_VERSION)


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "paperkit"})
    print("  downloading %s" % url)
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("content-length") or 0)
        done = 0
        report_at = 0
        with open(str(destination), "wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if total and done - report_at >= total // 10:
                    report_at = done
                    sys.stdout.write("\r  %d%%" % (done * 100 // total))
                    sys.stdout.flush()
    if total:
        sys.stdout.write("\r  100%\n")
    sys.stdout.flush()


def extract_member(archive: Path, kind: str, member: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "tar.gz":
        with tarfile.open(str(archive), "r:gz") as tar:
            try:
                handle = tar.extractfile(member)
            except KeyError:
                handle = None
            if handle is None:
                raise Failure("%s does not contain %s" % (archive.name, member))
            with open(str(destination), "wb") as out:
                shutil.copyfileobj(handle, out)
    else:
        with zipfile.ZipFile(str(archive)) as zf:
            try:
                handle = zf.open(member)
            except KeyError:
                raise Failure("%s does not contain %s" % (archive.name, member))
            with handle, open(str(destination), "wb") as out:
                shutil.copyfileobj(handle, out)
    if not is_windows():
        os.chmod(str(destination), 0o755)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_setup(args):
    asset, digest, kind, member = describe_asset()
    target = cached_pandoc()

    if target.is_file() and not args.force:
        version = pandoc_version(str(target))
        print("Pandoc %s already installed: %s" % (PANDOC_VERSION, target))
        if version:
            print("  reported version: %d.%d" % version)
        print("  use --force to reinstall")
        return 0

    if target.is_file() and args.force:
        target.unlink()

    url = RELEASE_URL.format(version=PANDOC_VERSION, asset=asset)
    print("Installing Pandoc %s (%s/%s)" % (PANDOC_VERSION, platform_family(), normalise_arch()))

    temp_dir = Path(tempfile.mkdtemp(prefix="paperkit-"))
    try:
        archive = temp_dir / asset
        download(url, archive)

        print("  verifying sha256")
        actual = sha256_of(archive)
        if actual != digest:
            raise Failure(
                "checksum mismatch for %s\n  expected %s\n  actual   %s"
                % (asset, digest, actual)
            )

        extract_member(archive, kind, member, target)
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)

    if sys.platform == "darwin":
        # Best effort: only matters if the archive was fetched by a browser.
        subprocess.run(
            ["xattr", "-d", "-r", "com.apple.quarantine", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    version = pandoc_version(str(target))
    if version is None:
        raise Failure("extracted Pandoc is not executable: %s" % target)

    print("Installed: %s (pandoc %d.%d)" % (target, version[0], version[1]))
    return 0


def journal_dir(root: Path, name: str) -> Path:
    return root / "journals" / name


def read_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise Failure("cannot read %s: %s" % (path, error))
    if not isinstance(value, dict):
        raise Failure("%s must contain a JSON object" % path)
    return value


def journal_profile(root: Path, name: str):
    if not isinstance(name, str) or not name or Path(name).name != name or "\\" in name or name in (".", ".."):
        raise Failure("invalid journal name: %s" % name)
    path = journal_dir(root, name) / "profile.json"
    return read_json(path) if path.is_file() else {}


def kit_path(root: Path, value: str):
    if not isinstance(value, str) or not value:
        raise Failure("profile paths must be non-empty strings")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise Failure("profile path must stay inside the repository: %s" % value)
    return path


def annotations_options(root: Path, path: Path):
    data = read_json(path)
    entries = data.get("reference-annotations", {})
    if not isinstance(entries, dict):
        raise Failure("reference-annotations must be an object keyed by citation key")
    if entries:
        try:
            start = date.fromisoformat(data["review-period-start"])
            end = date.fromisoformat(data["review-period-end"])
            if start > end:
                raise ValueError("review period is reversed")
            # A calendar two-year window, with Feb 29 handled explicitly.
            try:
                earliest = end.replace(year=end.year - 2)
            except ValueError:
                earliest = date(end.year - 2, 2, 28)
            if start < earliest:
                raise ValueError("review period exceeds two years")
            for key, entry in entries.items():
                if not isinstance(entry, dict) or entry.get("interest") not in ("*", "**"):
                    raise ValueError("%s: interest must be * or **" % key)
                if not isinstance(entry.get("text"), str) or not entry["text"].strip():
                    raise ValueError("%s: annotation text is required" % key)
                published = date.fromisoformat(entry["published"])
                if not start <= published <= end:
                    raise ValueError("%s: publication date is outside review period" % key)
        except (KeyError, TypeError, ValueError) as error:
            raise Failure("invalid annotations in %s: %s" % (path, error))
    return ["--metadata-file=%s" % arg_path(root, path)]


def journal_options(root: Path, name: str, annotation_path=None):
    profile = journal_profile(root, name)
    options = []
    if profile.get("annotations"):
        path = annotation_path or root / "reference-annotations.json"
        if path.is_file():
            options.extend(annotations_options(root, path))
    filters = profile.get("filters", [])
    if not isinstance(filters, list):
        raise Failure("profile filters must be a list")
    for value in filters:
        path = kit_path(root, value)
        if not path.is_file():
            raise Failure("missing journal filter: %s" % path)
        options.append("--lua-filter=%s" % arg_path(root, path))
    return options


def journal_assets(root: Path, name: str):
    directory = journal_dir(root, name)
    profile = journal_profile(root, name)
    csl = kit_path(root, profile["csl"]) if "csl" in profile else directory / ("%s.csl" % name)
    reference = directory / "templates" / "pandoc-reference.docx"
    appendix_reference = directory / "templates" / "appendix-reference.docx"
    return directory, csl, reference, appendix_reference


def export_assets(root: Path, args):
    """Resolve main-document styling independently of the journal's citations."""
    directory, csl, reference, appendix_reference = journal_assets(root, args.journal)
    for option in ("csl", "reference_doc"):
        value = getattr(args, option, None)
        if value is None:
            continue
        path = kit_path(root, value)
        if not path.is_file():
            raise Failure("missing configured %s: %s" % (option, path))
        if option == "csl":
            csl = path
        else:
            reference = path
    return directory, csl, reference, appendix_reference


def cmd_doctor(args):
    root = repo_root()
    problems = []
    warnings = []

    print("paperkit doctor")
    print("  repository   %s" % root)
    print("  journal      %s" % args.journal)
    journal_options(root, args.journal)
    print("  python       %s" % sys.version.split()[0])
    print("  platform     %s/%s" % (platform_family(), normalise_arch()))

    executable, version, origin = resolve_pandoc(args.pandoc, quiet=True)
    if executable is None:
        problems.append(
            "no usable Pandoc found - run: python3 paperkit.py setup"
        )
        print("  pandoc       MISSING")
    else:
        print("  pandoc       %d.%d  [%s]  %s" % (version[0], version[1], origin, executable))

    directory, csl, reference, appendix_reference = export_assets(root, args)
    print("  reference    %s" % arg_path(root, reference))
    print("  csl          %s" % arg_path(root, csl))
    if not directory.is_dir():
        problems.append("journal directory missing: %s" % directory)
    if not csl.is_file():
        warnings.append("no CSL style at %s (citations use the Pandoc default)" % csl)
    if not reference.is_file():
        problems.append("missing Word reference document: %s" % reference)
    if not appendix_reference.is_file():
        warnings.append(
            "no appendix template at %s - appendix.md will be skipped" % appendix_reference
        )

    manuscript = root / "manuscript.md"
    if not manuscript.is_file():
        warnings.append("manuscript.md not found - run: python3 paperkit.py new")
    bibliography = root / "references.bib"
    if not bibliography.is_file():
        warnings.append("references.bib not found (export it from Zotero + Better BibTeX)")

    legacy = root / "tools" / "bin" / "pandoc"
    if legacy.exists():
        warnings.append(
            "legacy vendored Pandoc found at %s - remove it, it must not be tracked by git" % legacy
        )

    # Pandoc emits style names such as `Author`; if the reference document does
    # not define them, Word silently falls back to Normal.
    style_checker = root / "journals" / "add_missing_styles.py"
    if style_checker.is_file() and reference.is_file():
        result = run(
            [sys.executable, str(style_checker), "--journal", args.journal,
             "--reference", str(reference), "--check"],
            cwd=root,
            capture=True,
        )
        if result.returncode == 1:
            warnings.append(
                "%s does not define every style Pandoc emits; run: "
                "python3 journals/add_missing_styles.py --journal %s"
                % (reference.name, args.journal)
            )
        elif result.returncode not in (0, 1):
            warnings.append(
                "style check failed: %s" % (result.stdout or "").strip().splitlines()[0]
                if (result.stdout or "").strip()
                else "style check failed"
            )

    if shutil.which("git"):
        inside = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture=True)
        if inside.returncode != 0:
            warnings.append("not inside a git work tree")
        else:
            tracked = run(["git", "ls-files", "output"], cwd=root, capture=True)
            if tracked.returncode == 0:
                # output/.gitkeep is intentional; anything else is a mistake.
                offenders = [
                    line
                    for line in tracked.stdout.split()
                    if not line.endswith(".gitkeep")
                ]
                if offenders:
                    warnings.append(
                        "generated files under output/ are tracked by git: %s"
                        % ", ".join(offenders[:3])
                    )
    else:
        warnings.append("git not found on PATH")

    print("")
    for message in warnings:
        print("  warn  %s" % message)
    for message in problems:
        print("  FAIL  %s" % message)
    if not warnings and not problems:
        print("  all checks passed")
    return 1 if problems else 0


SKELETON_MANUSCRIPT = """---
title: "Manuscript title"
author:
  - "First Author"
date: ""
---

## Abstract

Write the abstract here.

# Introduction

Write the introduction here.

# Results

### Result heading

Write the result here. Inline math is written $I(Y; Z)$ with single dollar
signs; wrapping it in backticks would turn it into a code span instead of a
formula. Display math uses double dollar signs:

$$
\\mathrm{ITCA} = \\frac{I(Y; Z)}{H(Y)}.
$$

<!-- Add a figure with, for example:
![Figure 1 caption.](figures/figure-1.png){#fig:overview width=85%}
-->

# Discussion

Write the discussion here.

# Methods

Write the methods here.

# References

::: {#refs}
:::
"""

SKELETON_APPENDIX = """---
title: "Supplementary Information"
---

# Supplementary Methods

Write supplementary methods here.

# Supplementary Results

Write supplementary results here.

# Supplementary Figures

<!-- Add a figure with, for example:
![Supplementary Figure 1 caption.](figures/supplementary-figure-1.png){#fig:supplementary-1 width=85%}
-->

# Supplementary Tables

# References

::: {#refs}
:::
"""

SKELETON_BIB = """% Export this file from Zotero with Better BibTeX, then cite in Markdown
% with keys such as [@Stuart2019]. Keep one bibliography per manuscript.
"""

SKELETON_METADATA = """bibliography: references.bib
link-citations: false
lang: en-US
"""

SKELETON_REPRODUCIBILITY = """# Reproducibility Record

## Toolchain

- paperkit: {kit}
- Pandoc: {pandoc}

## Code Snapshot (optional)

Fill this in only when the manuscript depends on an analysis repository. Delete
the section entirely if it does not.

- Code repository:
- Remote URL:
- Branch:
- Commit: record the exact SHA when a figure set or submission revision is frozen

## Analysis Record

Record the exact analysis entry point, configuration file, input data release,
and any random seeds for each figure or submission revision here. If figures are
produced by an analysis repository, record the entry point and commit SHA that
generated each one.
"""


def init_materials(root: Path):
    """Create local materials and versioned notes without replacing any content."""
    created = []
    for name in ("previous-drafts", "papers", "incoming", "private-notes"):
        directory = root / "materials" / name
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append("materials/%s/" % name)
    files = {
        "notes/literature/.gitkeep": "",
        "notes/outline.md": "# Writing outline\n\nRecord the review question, scope, and argument here.\n",
        "notes/search-log.md": (
            "# Literature search log\n\n"
            "Record databases, search dates, exact queries, and selection criteria.\n"
        ),
    }
    for name, content in sorted(files.items()):
        path = root / name
        if not path.exists():
            write_text(path, content)
            created.append(name)
    return created


def cmd_materials(args):
    root = repo_root()
    created = init_materials(root)
    print("Initialised writing materials in %s" % root)
    for name in created:
        print("  + %s" % name)
    print("  materials/ is git-ignored; back it up separately.")
    print("  notes/ is intended for version control; existing files are preserved.")
    return 0


def cmd_new(args):
    root = repo_root()
    if (root / "manuscript.md").exists() and not args.force:
        raise Failure(
            "manuscript.md already exists - this repository is already a manuscript\n"
            "  pass --force to overwrite the skeleton files"
        )

    created = []
    appendix = root / "appendix.tex"
    if args.latex_appendix and not os.path.lexists(appendix):
        template = root / "journals/nature/templates/appendix.tex"
        try:
            content = template.read_bytes()
            with appendix.open("xb") as output:
                output.write(content)
            created.append(appendix.name)
        except FileExistsError:
            pass  # Another process created the appendix first.
        except OSError as error:
            raise Failure("could not create LaTeX appendix: %s" % error) from error

    files = {
        "manuscript.md": SKELETON_MANUSCRIPT,
        "appendix.md": SKELETON_APPENDIX,
        "references.bib": SKELETON_BIB,
        "metadata.yaml": SKELETON_METADATA,
        "REPRODUCIBILITY.md": SKELETON_REPRODUCIBILITY.format(
            kit=args.kit or "<set me>", pandoc=PANDOC_VERSION
        ),
    }
    for name, content in sorted(files.items()):
        path = root / name
        if path.exists() and not args.force:
            continue
        write_text(path, content)
        created.append(name)

    for directory in ("figures", "tables", "output", "submissions"):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        keep = path / ".gitkeep"
        if not keep.exists():
            write_text(keep, "")
            created.append("%s/.gitkeep" % directory)

    created.extend(init_materials(root))

    print("Initialised manuscript skeleton in %s" % root)
    for name in created:
        print("  + %s" % name)
    print("")
    print("Next steps:")
    print("  1. python3 paperkit.py setup      # install the pinned Pandoc")
    print("  2. edit manuscript.md, references.bib, metadata.yaml")
    print("  3. python3 paperkit.py build")
    return 0


def arg_path(root: Path, path: Path) -> str:
    """Path for the pandoc command line, relative to root when possible.

    Pandoc records some options (notably `--csl`) in the DOCX metadata, so
    repository-relative paths keep the output identical across machines and
    operating systems. Forward slashes are emitted on every platform.
    """
    path = Path(path)
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return str(path)
    return relative.as_posix()


def build_one(root, executable, source, reference, csl, output, metadata, dry_run, extra_options=()):
    command = [executable, arg_path(root, source)]
    if metadata is not None:
        command.append("--metadata-file=%s" % arg_path(root, metadata))
    command.append("--citeproc")
    command.extend(extra_options)
    if csl is not None:
        command.append("--csl=%s" % arg_path(root, csl))
    command += [
        "--resource-path=.",
        "--reference-doc=%s" % arg_path(root, reference),
        "--output=%s" % arg_path(root, output),
    ]

    print("  %s -> %s" % (source.name, arg_path(root, output)))
    if dry_run:
        print("    %s" % " ".join(str(part) for part in command))
        return True

    output.parent.mkdir(parents=True, exist_ok=True)
    result = run(command, cwd=root)
    if result.returncode != 0:
        raise Failure("pandoc failed while building %s" % source.name)
    return True


def cmd_build(args):
    root = repo_root()
    executable, version, origin = resolve_pandoc(args.pandoc, quiet=True)
    if executable is None:
        raise Failure(
            "no usable Pandoc found\n"
            "  run: python3 paperkit.py setup\n"
            "  or install Pandoc yourself and put it on PATH"
        )

    directory, csl, reference, appendix_reference = export_assets(root, args)
    if not csl.is_file():
        print("  note: no CSL style at %s, using the Pandoc default" % csl)
        csl = None
    if not reference.is_file():
        raise Failure(
            "missing Word reference document: %s\n"
            "  place the journal template there (see README.md)" % reference
        )

    metadata = root / "metadata.yaml"
    if not metadata.is_file():
        metadata = None
    bibliography = root / "references.bib"
    if not bibliography.is_file():
        print("  note: references.bib not found, citations will not resolve")

    print(
        "paperkit build (%s, pandoc %d.%d from %s)"
        % (args.journal, version[0], version[1], origin),
        flush=True,
    )

    sources = [root / "manuscript.md"]
    if not sources[0].is_file():
        raise Failure("missing manuscript.md - run: python3 paperkit.py new")

    for source in sources:
        build_one(
            root,
            executable,
            source,
            reference,
            csl,
            root / "output" / (source.stem + ".docx"),
            metadata,
            args.dry_run,
            journal_options(root, args.journal),
        )

    if args.no_appendix:
        return 0

    appendix = root / "appendix.md"
    if not appendix.is_file():
        return 0
    if not appendix_reference.is_file():
        print("  skipping appendix.md: %s is missing" % appendix_reference)
        return 0

    build_one(
        root,
        executable,
        appendix,
        appendix_reference,
        csl,
        root / "output" / "appendix.docx",
        metadata,
        args.dry_run,
        journal_options(root, args.journal),
    )
    return 0



# Word counts use the source AST, without citeproc or generated bibliography.
WORD_PATTERN = re.compile(r"[^\W_]+(?:[’'\-‐‑][^\W_]+)*", re.UNICODE)


def count_manuscript(ast):
    counts = dict.fromkeys(("body", "abstract", "figure-legends", "references", "front-matter"), 0)
    warnings = set()
    sections = {"abstract": "abstract", "references": "references",
                "references and recommended reading": "references",
                "figure legends": "figure-legends", "figure captions": "figure-legends",
                "keywords": "front-matter"}

    def words(text, bucket):
        counts[bucket] += len(WORD_PATTERN.findall(text))
        if "TODO" in text:
            warnings.add("TODO placeholders are included; this is not a finished manuscript.")
        if re.search(r"[\u3400-\u9fff]", text):
            warnings.add("CJK text found; this tokenizer is intended for English prose.")

    def title(node):
        if isinstance(node, list):
            return "".join(title(x) for x in node)
        if isinstance(node, dict):
            if node.get("t") == "Str":
                return node["c"]
            if node.get("t") in ("Space", "SoftBreak", "LineBreak"):
                return " "
            return title(node.get("c", []))
        return ""

    def walk(node, bucket):
        if isinstance(node, list):
            for child in node:
                walk(child, bucket)
            return
        if not isinstance(node, dict):
            return
        kind, c = node.get("t"), node.get("c")
        if kind == "Str":
            words(c, bucket)
        elif kind in ("Code", "CodeBlock"):
            words(c[-1], bucket)
            warnings.add("Code is counted as text; review its treatment if present in the submission.")
        elif kind == "Math":
            counts[bucket] += 1
            warnings.add("Each math expression counts as one word; publisher/Word counts may differ.")
        elif kind in ("RawInline", "RawBlock"):
            if not (c[0] == "html" and re.fullmatch(r"\s*<!--.*?-->\s*", c[1], re.S)):
                warnings.add("Raw markup is not counted; review visible content before relying on the total.")
        elif kind == "Cite":
            for citation in c[0]:
                walk(citation.get("citationPrefix", []), bucket)
                walk(citation.get("citationSuffix", []), bucket)
        elif kind == "Image":
            # Figure captions are handled by Figure; an inline image has alt text only.
            warnings.add("Image alt text is excluded; put visible legends in a Figure or marked legend block.")
        elif kind == "Figure":
            walk(c[1][1], "figure-legends")  # long caption, not duplicate short caption
        elif kind == "Div":
            attr, blocks = c
            attributes = dict(attr[2])
            category = attributes.get("wordcount")
            if category is not None and category not in counts:
                raise Failure("unknown wordcount category: %s" % category)
            walk_blocks(blocks, category or ("references" if attr[0] == "refs" else bucket))
        elif kind == "Table":
            # Caption's short form repeats its long form. Cells remain counted.
            walk(c[1][1], bucket)
            walk(c[3:], bucket)
            warnings.add("Table captions/cells and box text are included unless explicitly classified.")
        elif kind in ("Link", "Span", "Header"):
            walk(c[1] if kind == "Link" else c[-1], bucket)
        else:
            walk(c, bucket)

    def walk_blocks(blocks, bucket):
        current, excluded_level = bucket, None
        for block in blocks:
            if block.get("t") == "Header":
                level, _, inlines = block["c"]
                name = title(inlines).strip().lower()
                if excluded_level is not None and level <= excluded_level:
                    current, excluded_level = bucket, None
                if name in sections:
                    current, excluded_level = sections[name], level
                    continue  # structural labels are not words
            walk(block, current)

    for key in ("title", "subtitle", "author", "date", "keywords"):
        walk(ast.get("meta", {}).get(key, []), "front-matter")
    walk(ast.get("meta", {}).get("abstract", []), "abstract")
    walk_blocks(ast["blocks"], "body")
    return counts, sorted(warnings)


def cmd_wordcount(args):
    root = repo_root()
    source = root / args.source
    if not source.is_file():
        raise Failure("missing manuscript source: %s" % source)
    config = read_json(root / "paperkit.json") if (root / "paperkit.json").is_file() else {}
    limit = args.limit if args.limit is not None else config.get("word_limit")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise Failure("word_limit / --limit must be a positive integer")
    executable, _, _ = resolve_pandoc(args.pandoc, quiet=True)
    if executable is None:
        raise Failure("no usable Pandoc found - run: python3 paperkit.py setup")
    command = [executable, str(source), "--from=markdown", "--to=json"]
    if (root / "metadata.yaml").is_file():
        command.append("--metadata-file=" + str(root / "metadata.yaml"))
    result = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8")
    if result.returncode:
        raise Failure("Pandoc could not parse manuscript: " + result.stderr.strip())
    counts, warnings = count_manuscript(json.loads(result.stdout))
    if result.stderr.strip():
        warnings.append(result.stderr.strip())
    over = limit is not None and counts["body"] > limit
    report = {"source": arg_path(root, source), "counts": counts, "limit": limit,
              "remaining": None if limit is None else limit - counts["body"],
              "status": "over-limit" if over else ("within-limit" if limit else "no-limit"),
              "warnings": warnings,
              "bibliography_note": "Source text only; generated bibliography and external annotations are excluded."}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("paperkit wordcount: %s" % report["source"])
        print("  body: %d words (includes section headings, tables and boxes)" % counts["body"])
        for category, count in counts.items():
            if category != "body":
                print("  excluded %-16s %d" % (category + ":", count))
        print("  " + report["bibliography_note"])
        if limit:
            print("  %s: limit %d; %d words %s" % (report["status"], limit,
                  abs(report["remaining"]), "over" if over else "remaining"))
        else:
            print("  no limit configured; set paperkit.json word_limit or --limit")
        for warning in warnings:
            print("  review: " + warning)
    return 1 if over else 0


VALIDATION_MEMBERS = ("word/document.xml", "word/styles.xml", "word/numbering.xml")


def docx_member(path: Path, name: str):
    """Return the bytes of one part inside a DOCX package, or None."""
    try:
        with zipfile.ZipFile(str(path)) as archive:
            try:
                return archive.read(name)
            except KeyError:
                return None
    except (zipfile.BadZipFile, OSError):
        return None


def cmd_validate(args):
    """Rebuild validation/*.md and compare against the committed fixtures.

    A fixture `x.docx` is built with the journal reference document; a fixture
    `x-default.docx` is built with Pandoc's own reference document, which is the
    baseline showing what the journal template changes.
    """
    root = repo_root()
    profile = journal_profile(root, args.journal)
    vdir = kit_path(root, profile.get("validation", "validation"))
    if not vdir.is_dir():
        raise Failure("no validation directory at %s" % vdir)

    executable, version, origin = resolve_pandoc(args.pandoc, quiet=True)
    if executable is None:
        raise Failure("no usable Pandoc found - run: python3 paperkit.py setup")

    _directory, csl, reference, _appendix = journal_assets(root, args.journal)
    if not reference.is_file():
        raise Failure("missing Word reference document: %s" % reference)
    bibliography = vdir / "references.bib"

    sources = sorted(vdir.glob("*.md"))
    if not sources:
        raise Failure("no validation/*.md sources found in %s" % vdir)

    print("paperkit validate (pandoc %d.%d from %s)" % (version[0], version[1], origin))

    temp_dir = Path(tempfile.mkdtemp(prefix="paperkit-validate-"))
    print("  rebuilt copies: %s" % temp_dir)

    stale = []
    for source in sources:
        cases = [(vdir / (source.stem + ".docx"), True)]
        default_fixture = vdir / (source.stem + "-default.docx")
        if default_fixture.is_file():
            cases.append((default_fixture, False))

        for fixture, use_reference in cases:
            built = temp_dir / fixture.name
            command = [executable, arg_path(root, source), "--citeproc"]
            command.extend(journal_options(root, args.journal, vdir / "reference-annotations.json"))
            if bibliography.is_file():
                command.append("--bibliography=%s" % arg_path(root, bibliography))
            if csl.is_file():
                command.append("--csl=%s" % arg_path(root, csl))
            if use_reference:
                command.append("--reference-doc=%s" % arg_path(root, reference))
            command += ["--resource-path=.", "--output=%s" % built]

            if args.verbose:
                print("         %s" % " ".join(str(part) for part in command))

            result = run(command, cwd=root, capture=True)
            if result.returncode != 0 or not built.is_file():
                failures = (result.stdout or "").strip().splitlines()
                print("  ERROR  %s" % fixture.name)
                for line in failures:
                    print("         %s" % line)
                stale.append(fixture.name)
                continue

            if not fixture.is_file():
                print("  new    %s" % fixture.name)
                stale.append(fixture.name)
            else:
                changed = [
                    name
                    for name in VALIDATION_MEMBERS
                    if docx_member(built, name) != docx_member(fixture, name)
                ]
                if not changed:
                    print("  ok     %s" % fixture.name)
                    continue
                print("  DIFF   %s  (%s)" % (fixture.name, ", ".join(changed)))
                stale.append(fixture.name)

            if args.update:
                shutil.copyfile(str(built), str(fixture))
                print("         fixture updated")

    if stale and not args.update:
        print("")
        print("  %d fixture(s) differ from a fresh build." % len(stale))
        print("  Inspect the rebuilt copies above, then either fix the pipeline or")
        print("  refresh the baseline with: python3 paperkit.py validate --update")
        return 1
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="paperkit",
        description="Cross-platform manuscript build helper (Markdown + Pandoc -> DOCX).",
    )
    parser.add_argument("--journal", help="journal profile (default: paperkit.json, then nature)")
    subparsers = parser.add_subparsers(dest="command")

    setup = subparsers.add_parser("setup", help="install the pinned Pandoc into the user cache")
    setup.add_argument("--force", action="store_true", help="reinstall even if present")
    setup.set_defaults(func=cmd_setup)

    doctor = subparsers.add_parser("doctor", help="check the environment and journal assets")
    doctor.add_argument("--pandoc", help="path to a specific Pandoc executable")
    doctor.set_defaults(func=cmd_doctor)

    new = subparsers.add_parser("new", help="create the manuscript skeleton in this repository")
    new.add_argument("--force", action="store_true", help="overwrite existing skeleton files")
    new.add_argument("--kit", help="value recorded as the paperkit version in REPRODUCIBILITY.md")
    new.add_argument("--latex-appendix", action="store_true",
                     help="copy the Nature-style appendix.tex template if absent, even with --force")
    new.set_defaults(func=cmd_new)

    materials = subparsers.add_parser(
        "materials", help="add local materials and versioned notes without overwriting files"
    )
    materials.set_defaults(func=cmd_materials)

    validate = subparsers.add_parser(
        "validate",
        help="rebuild validation/*.md and compare with the committed fixtures",
    )
    validate.add_argument("--pandoc", help="path to a specific Pandoc executable")
    validate.add_argument(
        "--update",
        action="store_true",
        help="overwrite the fixtures with the freshly built documents",
    )
    validate.add_argument("--verbose", action="store_true", help="print the pandoc commands")
    validate.set_defaults(func=cmd_validate)

    build = subparsers.add_parser("build", help="export manuscript.md and appendix.md to DOCX")
    build.add_argument("--pandoc", help="path to a specific Pandoc executable")
    build.add_argument("--no-appendix", action="store_true", help="skip appendix.md")
    build.add_argument("--dry-run", action="store_true", help="print the pandoc command without running it")
    build.set_defaults(func=cmd_build)

    for subparser in (doctor, build):
        subparser.add_argument(
            "--reference-doc", help="main Word template path inside the repository (overrides paperkit.json)",
        )
        subparser.add_argument(
            "--csl", help="citation style path inside the repository (overrides paperkit.json)",
        )

    wordcount = subparsers.add_parser("wordcount", help="count body words separately from excluded material")
    wordcount.add_argument("--source", default="manuscript.md", help="Markdown source (default: manuscript.md)")
    wordcount.add_argument("--limit", type=int, help="override manuscript-owned word_limit")
    wordcount.add_argument("--pandoc", help="path to Pandoc")
    wordcount.add_argument("--json", action="store_true", help="print machine-readable report")
    wordcount.set_defaults(func=cmd_wordcount)

    for subparser in (doctor, new, validate, build, wordcount):
        subparser.add_argument("--journal", default=argparse.SUPPRESS, help="override journal profile")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        config_path = repo_root() / "paperkit.json"
        config = read_json(config_path) if config_path.is_file() else {}
        args.journal = args.journal or os.environ.get("JOURNAL") or config.get("journal", "nature")
        if args.command in ("doctor", "build"):
            for option in ("reference_doc", "csl"):
                if getattr(args, option, None) is None:
                    setattr(args, option, config.get(option))
        journal_profile(repo_root(), args.journal)
        return args.func(args)
    except Failure as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
