"""Generate the checked-in JSON Schema for every contract and every result.

Both file sets are derived from the registries in `contracts.py`, so a contract cannot
ship without a schema on each side. Output is byte-deterministic — sorted keys, two-space
indent, trailing newline — because the freshness test compares bytes, not structures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from motor_costos.contracts import CONTRACTS, RESULTS

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def schema_filename(contract_version: str, *, result: bool = False) -> str:
    """`cost-cascade.v1` -> `cost-cascade-v1.schema.json`."""
    stem = contract_version.replace(".v", "-v")
    suffix = "-result" if result else ""
    name, _, version = stem.rpartition("-")
    return f"{name}{suffix}-{version}.schema.json"


def render_schemas() -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    for registry, is_result in ((CONTRACTS, False), (RESULTS, True)):
        for contract_version, model in registry.items():
            payload = json.dumps(TypeAdapter(model).json_schema(), sort_keys=True, indent=2) + "\n"
            rendered[schema_filename(contract_version, result=is_result)] = payload.encode("utf-8")
    return rendered


def write_schemas(directory: Path | None = None) -> list[Path]:
    target = SCHEMA_DIR if directory is None else directory
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in render_schemas().items():
        path = target / name
        path.write_bytes(content)
        written.append(path)
    return written


def main() -> int:
    for path in write_schemas():
        print(path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
