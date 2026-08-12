"""Schema freshness and the capability registry, both by anti-drift.

The schemas are generated from the models, so the only failure mode is a stale checked-in
file. That is compared byte for byte.

The capability check closes the matching gap: restating the contract version tuple in the
Capabilities model, with nothing pinning it to the registry, lets a new contract ship
undeclared. Here both derive from `CONTRACTS`, and this asserts it.
"""

from __future__ import annotations

import json

from motor_costos import capabilities
from motor_costos.contracts import CONTRACTS, RESULTS
from motor_costos.schemas import (
    SCHEMA_DIR,
    main,
    render_schemas,
    schema_filename,
    write_schemas,
)


def test_checked_in_schemas_are_fresh():
    for name, content in render_schemas().items():
        checked_in = (SCHEMA_DIR / name).read_bytes()
        assert checked_in == content, f"schema {name} is stale; run motor-costos-schemas"


def test_every_contract_has_an_input_and_a_result_schema():
    rendered = set(render_schemas())
    expected = {schema_filename(name) for name in CONTRACTS}
    expected |= {schema_filename(name, result=True) for name in RESULTS}
    assert rendered == expected
    assert set(CONTRACTS) == set(RESULTS)


def test_no_stray_schema_files_are_checked_in():
    on_disk = {path.name for path in SCHEMA_DIR.glob("*.schema.json")}
    assert on_disk == set(render_schemas())


def test_capabilities_declare_exactly_the_registered_contracts():
    assert capabilities().contract_versions == tuple(CONTRACTS)


def test_capabilities_are_honest_about_what_the_engine_refuses():
    caps = capabilities()
    assert caps.currency_conversion is False
    assert caps.unit_conversion is False
    assert caps.publication == "none"
    assert caps.max_nesting_depth == 1


def test_capabilities_publish_the_rounding_default():
    caps = capabilities()
    assert caps.default_rounding_mode == "final"
    assert caps.default_money_scale == 4
    assert caps.engine_precision == 28
    assert set(caps.rounding_modes) == {"exact", "final", "per-stage"}


def test_amounts_are_declared_as_strings_never_numbers():
    """A schema that admits `number` invites a consumer to parse money into a float.

    Both sides are checked. Pydantic's default for a Decimal is `anyOf[number, string]`,
    which is a precision hole at the transport edge in either direction.
    """
    for name in render_schemas():
        text = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        document = json.loads(text)
        for definition in document.get("$defs", {}).values():
            for field, spec in definition.get("properties", {}).items():
                assert spec.get("type") != "number", f"{name}:{field}"
        assert '"type": "number"' not in text, name


def test_write_schemas_round_trips_to_disk(tmp_path):
    """`motor-costos-schemas` must write exactly what the freshness test compares."""
    written = write_schemas(tmp_path)
    assert {path.name for path in written} == set(render_schemas())
    for path in written:
        assert path.read_bytes() == render_schemas()[path.name]


def test_the_console_script_entry_point_runs_and_leaves_the_files_fresh(capsys):
    """`motor-costos-schemas` is advertised in pyproject, so it is exercised."""
    assert main() == 0
    printed = capsys.readouterr().out.split()
    assert set(printed) == set(render_schemas())
    for name, content in render_schemas().items():
        assert (SCHEMA_DIR / name).read_bytes() == content
