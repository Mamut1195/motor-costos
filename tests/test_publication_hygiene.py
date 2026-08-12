"""Nothing internal reaches a published file.

This engine was translated from a prior in-house implementation. Every technical argument
that translation produced is public — the rounding decision, the choice against a units
library, the parametrised taxonomy, and all the pinned oracle values. The **provenance**
of those arguments is not: the internal application's module paths and the machine paths
of whoever did the reading.

Sanitising once makes that true today. This makes it true tomorrow: a docstring edited
back into citing an internal path fails the suite instead of shipping.

Two kinds of pattern, deliberately kept apart:

- **Structural** patterns live here. A Windows home directory or a cloud-drive path is a
  shape, not a secret, so naming it costs nothing.
- **Identifying** patterns live in `_private/forbidden-patterns.txt`, which is gitignored.
  A public test that hardcodes the strings it forbids publishes them itself — which is
  exactly the mistake the first version of this file made, carrying the internal
  application name and the developer's name as literal regexes into a public commit.

On a fresh clone the private list is absent, so the identifying scan reports itself as
unavailable rather than passing silently. It runs where it matters: on the machine that
is about to push.

If a pattern fires, the fix is to reword the published file, never to weaken the pattern.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PRIVATE_PATTERNS = REPO / "_private" / "forbidden-patterns.txt"

#: Shapes, not secrets. Safe to name in a published file.
#:
#: Matched against a copy of each line with backslashes turned into forward slashes, so
#: the patterns never need to escape a path separator. Writing `[\\/]` by hand is how the
#: first version of the home-directory check silently ended up matching only forward
#: slashes; normalising the text instead removes the whole class of mistake.
STRUCTURAL = {
    "windows user path": re.compile(r"[A-Za-z]:/Users/", re.I),
    "cloud drive path": re.compile(r"\bOneDrive\b", re.I),
    "home directory of whoever runs this": re.compile(
        rf"/{re.escape(Path.home().name)}/" if Path.home().name else r"(?!x)x", re.I
    ),
}


def normalise(text: str) -> str:
    """Backslashes to forward slashes, so one pattern covers both path flavours."""
    return text.replace("\\", "/")

#: This suite has to describe what it forbids, and .gitignore has to name what it excludes.
ALLOWED = {"tests/test_publication_hygiene.py", ".gitignore"}


def load_identifying_patterns() -> dict[str, re.Pattern[str]] | None:
    if not PRIVATE_PATTERNS.is_file():
        return None
    patterns = {}
    for raw in PRIVATE_PATTERNS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns[line] = re.compile(line, re.I)
    return patterns


def published_files() -> list[Path]:
    """Every file git would publish, straight from git rather than a glob.

    Asking git rather than walking the tree is the point: a file excluded by `.gitignore`
    is exactly a file this test should not scan, and a file git tracks is exactly one it
    must. Before the first commit there is no index, so fall back to the working tree
    minus the directories that are ignored by construction.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=False
    )
    if result.returncode == 0 and result.stdout.strip("\0"):
        return [REPO / name for name in result.stdout.split("\0") if name]

    skip = {
        "_private",
        ".atl",  # editor tooling cache, full of absolute paths to the authoring machine
        ".claude",
        ".venv",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    return [
        path
        for path in REPO.rglob("*")
        if path.is_file() and not any(part in skip for part in path.relative_to(REPO).parts)
    ]


def scannable() -> list[Path]:
    text_suffixes = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".cfg", ".txt", ""}
    return [
        path
        for path in published_files()
        if path.suffix.lower() in text_suffixes
        and path.relative_to(REPO).as_posix() not in ALLOWED
    ]


def offences_for(pattern: re.Pattern[str]) -> list[str]:
    found = []
    for path in scannable():
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, text in enumerate(content.splitlines(), start=1):
            if pattern.search(normalise(text)):
                found.append(f"{path.relative_to(REPO).as_posix()}:{number}: {text.strip()}")
    return found


def test_the_structural_patterns_tell_paths_from_prose():
    """The guard guarding the guard.

    A scanner that cannot fail for the reason it states is worth as much as a test that
    cannot. Two mistakes are pinned here because both were actually made: a home-directory
    name matched as a bare word (CI runs as `runner`, and "a Windows runner" is prose), and
    a hand-escaped `[\\\\/]` class that quietly matched only forward slashes, so no Windows
    path was ever caught.
    """
    home = re.compile(r"/runner/", re.I)
    windows = STRUCTURAL["windows user path"]
    win_path = normalise("C:" + chr(92) + "Users" + chr(92) + "runner" + chr(92) + "Documents")

    assert home.search(normalise("/home/runner/work/repo")), "posix home path must match"
    assert home.search(win_path), "windows home path must match once normalised"
    assert not home.search(normalise("GitHub's windows-latest runner sets autocrlf")), (
        "prose containing the home name must not match"
    )
    assert windows.search(win_path), "a windows user path must match once normalised"
    assert not windows.search(normalise("see the Users guide")), "prose must not match"


def test_there_is_something_to_scan():
    """A scan over zero files passes vacuously, which is worse than no scan at all."""
    paths = scannable()
    assert len(paths) >= 20, f"only {len(paths)} files scanned; the discovery is broken"
    names = {path.relative_to(REPO).as_posix() for path in paths}
    assert "README.md" in names
    assert "src/motor_costos/cascade.py" in names
    assert "docs/PROVENANCE.md" in names


@pytest.mark.parametrize("label", sorted(STRUCTURAL))
def test_no_published_file_carries_a_machine_path(label):
    offences = offences_for(STRUCTURAL[label])
    assert not offences, f"{label} found in published files:\n" + "\n".join(offences)


def test_no_published_file_carries_an_identifying_reference():
    """The identifying scan. Skips loudly on a fresh clone rather than passing silently."""
    patterns = load_identifying_patterns()
    if patterns is None:
        pytest.skip(
            "_private/forbidden-patterns.txt is absent, so the identifying scan cannot run. "
            "This is expected on a fresh clone and in CI; it must pass on the machine "
            "that pushes."
        )
    assert patterns, "the private pattern file exists but declares no patterns"
    offences = {
        label: found for label, pattern in patterns.items() if (found := offences_for(pattern))
    }
    assert not offences, "identifying references found in published files:\n" + "\n".join(
        f"[{label}]\n  " + "\n  ".join(lines) for label, lines in offences.items()
    )


def test_the_private_directory_is_not_tracked():
    tracked = {path.relative_to(REPO).as_posix() for path in published_files()}
    leaked = {name for name in tracked if name.startswith("_private/")}
    assert not leaked, f"private material is tracked by git: {sorted(leaked)}"


def test_the_build_brief_is_not_published():
    """It carries absolute machine paths and the internal application's location."""
    tracked = {path.relative_to(REPO).as_posix() for path in published_files()}
    assert "motor-costos.md" not in tracked


def test_the_private_directory_still_holds_the_audit_trail():
    """Sanitising must not have destroyed the provenance, only relocated it."""
    private = REPO / "_private"
    if not private.is_dir():
        pytest.skip("_private/ is untracked, so a fresh clone does not have it")
    for name in (
        "PROVENANCE-full.md",
        "REFERENCE-DEFECTS.md",
        "forbidden-patterns.txt",
        "motor-costos.md",
        "README.md",
    ):
        assert (private / name).is_file(), f"_private/{name} is missing"


def test_the_licence_is_the_published_one():
    """A file declaring itself confidential must never sit in a public repository."""
    licence = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in licence
    assert "confidential" not in licence.lower()
    assert "LicenseRef" not in (REPO / "pyproject.toml").read_text(encoding="utf-8")
