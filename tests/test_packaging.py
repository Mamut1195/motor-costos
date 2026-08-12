"""What the package claims about itself, checked against what it ships.

A distribution can lie about itself in ways no amount of testing the engine would
notice, because the lie lives in the metadata rather than the behaviour. This file
covers the one that shipped: `Typing :: Typed` was declared while the PEP 561 marker
was absent, so every consumer type-checking against this engine silently received
`Any` instead of the contracts it spent its whole design protecting.

Scope, deliberately stated: these tests pin the **claim**, not the **artifact**. That
the marker survives into the built wheel is a separate question -- the defect was
precisely that a file can exist in a repository and never reach the package a consumer
installs -- and CI proves it by building the wheel and looking inside. Neither check
subsumes the other, so neither should be removed on account of the other existing.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKER = REPO / "src" / "motor_costos" / "py.typed"
TYPED_CLASSIFIER = "Typing :: Typed"


def pyproject() -> dict:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_typed_claim_and_the_pep_561_marker_back_each_other():
    """Either one without the other is a package that lies, in one direction or the other.

    The classifier alone tells a consumer the annotations are usable when a type checker
    will ignore them. The marker alone ships usable annotations that nothing advertises.
    """
    classifiers = pyproject()["project"]["classifiers"]

    assert TYPED_CLASSIFIER in classifiers, (
        "the package dropped its typing claim; remove the marker too, or restore it"
    )
    assert MARKER.is_file(), (
        f"{TYPED_CLASSIFIER} is declared but {MARKER.name} is missing, so PEP 561 makes "
        "a type checker ignore every annotation in this package"
    )


def test_the_marker_is_empty_rather_than_partial():
    """PEP 561 ignores the contents -- except that `partial` means something else.

    A marker reading `partial` declares stub-only, incomplete coverage. The annotations
    here are inline and complete, so the file stays empty and says so by being empty.
    """
    assert MARKER.read_text(encoding="utf-8").strip() == ""
