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
import hashlib
import os
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


def journal_assets(root: Path, name: str):
    directory = journal_dir(root, name)
    csl = directory / ("%s.csl" % name)
    reference = directory / "templates" / "pandoc-reference.docx"
    appendix_reference = directory / "templates" / "appendix-reference.docx"
    return directory, csl, reference, appendix_reference


def cmd_doctor(args):
    root = repo_root()
    problems = []
    warnings = []

    print("paperkit doctor")
    print("  repository   %s" % root)
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

    directory, csl, reference, appendix_reference = journal_assets(root, args.journal)
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

    if shutil.which("git"):
        inside = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture=True)
        if inside.returncode != 0:
            warnings.append("not inside a git work tree")
        else:
            tracked = run(["git", "ls-files", "output"], cwd=root, capture=True)
            if tracked.returncode == 0 and tracked.stdout.strip():
                warnings.append("generated files under output/ are tracked by git")
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

Write the result here. Inline math uses `$I(Y; Z)$`.

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

## Code Snapshot

- Code repository:
- Remote URL:
- Branch:
- Commit: record the exact SHA when a figure set or submission revision is frozen

## Analysis Record

Record the exact analysis entry point, configuration file, input data release,
and any random seeds for each figure or submission revision here.
"""


def cmd_new(args):
    root = repo_root()
    if (root / "manuscript.md").exists() and not args.force:
        raise Failure(
            "manuscript.md already exists - this repository is already a manuscript\n"
            "  pass --force to overwrite the skeleton files"
        )

    created = []
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

    print("Initialised manuscript skeleton in %s" % root)
    for name in created:
        print("  + %s" % name)
    print("")
    print("Next steps:")
    print("  1. python3 paperkit.py setup      # install the pinned Pandoc")
    print("  2. edit manuscript.md, references.bib, metadata.yaml")
    print("  3. python3 paperkit.py build")
    return 0


def relative_to(root: Path, path: Path) -> str:
    """Path relative to the repository root, always with forward slashes.

    Pandoc records some options (notably `--csl`) in the DOCX metadata, so
    passing repository-relative paths keeps the output identical across
    machines and operating systems.
    """
    return os.path.relpath(str(path), str(root)).replace(os.sep, "/")


def build_one(root, executable, source, reference, csl, output, metadata, dry_run):
    command = [executable, relative_to(root, source)]
    if metadata is not None:
        command.append("--metadata-file=%s" % relative_to(root, metadata))
    command.append("--citeproc")
    if csl is not None:
        command.append("--csl=%s" % relative_to(root, csl))
    command += [
        "--resource-path=.",
        "--reference-doc=%s" % relative_to(root, reference),
        "--output=%s" % relative_to(root, output),
    ]

    print("  %s -> %s" % (source.name, relative_to(root, output)))
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

    directory, csl, reference, appendix_reference = journal_assets(root, args.journal)
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
    )
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="paperkit",
        description="Cross-platform manuscript build helper (Markdown + Pandoc -> DOCX).",
    )
    parser.add_argument("--journal", default="nature", help="journal asset set under journals/ (default: nature)")
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
    new.set_defaults(func=cmd_new)

    build = subparsers.add_parser("build", help="export manuscript.md and appendix.md to DOCX")
    build.add_argument("--pandoc", help="path to a specific Pandoc executable")
    build.add_argument("--no-appendix", action="store_true", help="skip appendix.md")
    build.add_argument("--dry-run", action="store_true", help="print the pandoc command without running it")
    build.set_defaults(func=cmd_build)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except Failure as error:
        print("error: %s" % error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
