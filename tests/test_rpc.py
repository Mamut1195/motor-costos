"""The JSON-RPC sidecar: framing, bounds, and what never leaks out of it."""

from __future__ import annotations

import io
import json
import sys
from decimal import Decimal

import pytest

from motor_costos import rpc
from motor_costos.rpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_RPC_LINE_BYTES,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    handle_line,
)

CASCADE_PARAMS = {
    "categories": ["MAT", "MO"],
    "labour_category": "MO",
    "lines": [
        {
            "resource_id": "labour",
            "category": "MO",
            "quantity": "1",
            "unit_price": "25.00",
            "waste_pct": "0",
            "currency": "USD",
        }
    ],
    "factors": {
        "tool_wear_pct": "5.00",
        "safety_equipment_pct": "3.00",
        "indirect_cost_pct": "20.00",
        "financing_pct": "2.00",
        "utility_pct": "12.00",
        "tax_pct": "16.00",
    },
}


def call(method: str, params=None, request_id=1, jsonrpc="2.0"):
    request = {"jsonrpc": jsonrpc, "method": method}
    if params is not None:
        request["params"] = params
    if request_id is not None:
        request["id"] = request_id
    return handle_line(json.dumps(request))


def test_the_oracle_survives_the_transport_intact():
    """42.9360 over the wire, as a string, not a float.

    `subtotal_3` carries trailing zeros because that is the exponent the reference's own
    arithmetic produces: `25.00 * 5.00` is `125.0000`, and dividing by 100 preserves the
    scale, so the exponent accumulates down the chain. The reference's oracle passes
    against `Decimal("37.01376")` only because Decimal compares by value. The engine
    reproduces the reference exponent rather than silently renormalising it; consumers
    compare numerically. See `test_cascade.test_stage_exponents_match_the_reference`.
    """
    response = json.loads(call("cost.cascade.v1", CASCADE_PARAMS))
    assert response["result"]["success"] is True
    assert response["result"]["unit_cost"] == "42.9360"
    stages = {s["name"]: s["amount"] for s in response["result"]["stages"]}
    assert Decimal(stages["subtotal_3"]) == Decimal("37.01376")
    assert stages["subtotal_3"] == "37.0137600000"


def test_dimension_check_over_the_wire():
    response = json.loads(
        call("dimension.check.v1", {"quantity_field": "volume", "unit_category": "length"})
    )
    assert response["result"]["compatible"] is False
    assert response["result"]["expected_field"] == "length"


def test_capabilities_takes_no_parameters():
    assert json.loads(call("engine.capabilities.v1"))["result"]["engine"] == "motor-costos"
    assert json.loads(call("engine.capabilities.v1", {"verbose": True}))["error"]["code"] == (
        INVALID_PARAMS
    )


def test_a_float_amount_is_refused_at_the_transport_edge():
    """JSON has one number type and it is a double. A price sent as 25.0 has already
    lost precision, so the wire refuses it exactly as the in-process API does."""
    params = json.loads(json.dumps(CASCADE_PARAMS))
    params["lines"][0]["unit_price"] = 25.0
    response = json.loads(call("cost.cascade.v1", params))
    assert response["error"]["code"] == INVALID_PARAMS
    assert "lines/0/unit_price" in response["error"]["message"]


def test_non_finite_constants_are_rejected_at_any_depth():
    for constant in ("NaN", "Infinity", "-Infinity"):
        line = f'{{"jsonrpc":"2.0","id":1,"method":"cost.cascade.v1","params":{{"x":{constant}}}}}'
        assert json.loads(handle_line(line))["error"]["code"] == PARSE_ERROR


def test_malformed_json_is_a_parse_error():
    assert json.loads(handle_line("{not json"))["error"]["code"] == PARSE_ERROR


def test_a_missing_or_wrong_protocol_version_is_an_invalid_request():
    assert json.loads(call("cost.cascade.v1", jsonrpc="1.0"))["error"]["code"] == INVALID_REQUEST
    assert json.loads(handle_line('{"method":"x","id":1}'))["error"]["code"] == INVALID_REQUEST


def test_an_unknown_method_is_reported_as_such():
    assert json.loads(call("cost.cascade.v2", {}))["error"]["code"] == METHOD_NOT_FOUND


def test_a_boolean_request_id_is_invalid():
    """`true` is an int in Python and would silently correlate with 1."""
    line = '{"jsonrpc":"2.0","id":true,"method":"engine.capabilities.v1"}'
    assert json.loads(handle_line(line))["error"]["code"] == INVALID_REQUEST


def test_a_notification_gets_no_response():
    assert call("engine.capabilities.v1", request_id=None) is None
    assert call("cost.cascade.v2", {}, request_id=None) is None


def test_an_oversized_line_is_refused():
    """The check at the API boundary. `handle_line` receives a whole string by
    construction; the reader that must never assemble one is tested separately below."""
    line = '{"jsonrpc":"2.0","id":1,"method":"x","params":"%s"}' % ("a" * MAX_RPC_LINE_BYTES)
    response = json.loads(handle_line(line))
    assert response["error"]["code"] == INVALID_REQUEST
    assert response["error"]["message"] == "Request too large"


def test_errors_never_carry_a_path_a_traceback_or_a_caller_value():
    params = json.loads(json.dumps(CASCADE_PARAMS))
    params["lines"][0]["unit_price"] = "-1"
    message = json.loads(call("cost.cascade.v1", params))["error"]["message"]
    assert "Traceback" not in message
    assert "\\" not in message
    assert "/Users" not in message
    assert "-1" not in message
    assert "pydantic" not in message.lower()


def test_a_domain_refusal_is_a_result_not_a_fault():
    """Mixed currencies are a diagnostic inside a successful transport exchange, not a
    JSON-RPC error: the call worked, the composition did not."""
    params = json.loads(json.dumps(CASCADE_PARAMS))
    params["lines"].append(
        {
            "resource_id": "cement",
            "category": "MAT",
            "quantity": "1",
            "unit_price": "10",
            "waste_pct": "0",
            "currency": "PEN",
        }
    )
    response = json.loads(call("cost.cascade.v1", params))
    assert "error" not in response
    assert response["result"]["success"] is False
    assert response["result"]["diagnostics"][0]["code"] == 3200
    assert response["result"]["unit_cost"] is None


def test_an_unbounded_quantity_is_a_result_not_an_internal_error():
    """A quantity no scale can quantise is a composition problem, not a transport one.

    It used to raise out of the engine and arrive here as `Internal error`, which tells
    a caller the sidecar is broken when in fact their number is.
    """
    params = json.loads(json.dumps(CASCADE_PARAMS))
    params["lines"][0]["quantity"] = "1e30"
    response = json.loads(call("cost.cascade.v1", params))
    assert "error" not in response
    assert response["result"]["success"] is False
    assert [d["code"] for d in response["result"]["diagnostics"]] == [3003]
    assert response["result"]["unit_cost"] is None


def test_the_response_is_byte_stable():
    first = call("cost.cascade.v1", CASCADE_PARAMS)
    second = call("cost.cascade.v1", CASCADE_PARAMS)
    assert first == second


def test_internal_error_code_is_reserved_and_unused_on_the_happy_path():
    response = json.loads(call("cost.cascade.v1", CASCADE_PARAMS))
    assert response.get("error", {}).get("code") != INTERNAL_ERROR


@pytest.mark.parametrize("params", ["a string", 42, ["a", "list"], True])
def test_params_that_are_not_an_object_are_invalid(params):
    assert json.loads(call("cost.cascade.v1", params))["error"]["code"] == INVALID_PARAMS


def test_an_unexpected_engine_failure_becomes_an_internal_error_with_no_detail(monkeypatch):
    """The one path that could leak a traceback. It must not, so it is exercised.

    A bare `except Exception` is only trustworthy if something proves what comes out of
    it; leaving it uncovered is how a leak ships.
    """

    # A synthetic path, deliberately not shaped like a real developer's home directory:
    # tests/test_publication_hygiene.py scans for those, and a fixture is not an excuse.
    def explode(_contract):
        raise RuntimeError("D:/build/internal/pricing_service.py exploded at line 12")

    monkeypatch.setattr(rpc, "compute_cascade", explode)
    response = json.loads(call("cost.cascade.v1", CASCADE_PARAMS))
    assert response["error"]["code"] == INTERNAL_ERROR
    assert response["error"]["message"] == "Internal error"
    assert "pricing_service" not in json.dumps(response)
    assert "exploded" not in json.dumps(response)
    assert "D:/" not in json.dumps(response)


def test_an_unexpected_failure_on_a_notification_stays_silent(monkeypatch):
    monkeypatch.setattr(rpc, "compute_cascade", lambda _c: 1 / 0)
    assert call("cost.cascade.v1", CASCADE_PARAMS, request_id=None) is None


def test_main_answers_one_line_per_request_and_skips_blanks(monkeypatch, capsys):
    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "engine.capabilities.v1"}),
                "",
                json.dumps({"jsonrpc": "2.0", "method": "engine.capabilities.v1"}),  # notification
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "nope"}),
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(sys, "stdin", stdin)
    assert rpc.main() == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 2, "the notification must produce no line"
    assert [json.loads(line)["id"] for line in lines] == [1, 2]
    assert json.loads(lines[1])["error"]["code"] == METHOD_NOT_FOUND


class EndlessLine:
    """A stream carrying one line that never ends.

    A reader that assembles a whole line before judging its size cannot survive this:
    it either never returns or grows without bound. The byte budget makes that failure
    an assertion instead of a hung suite.
    """

    def __init__(self, budget: int) -> None:
        self.served = 0
        self.budget = budget

    def read(self, size: int) -> str:
        if self.served > self.budget:
            raise AssertionError(
                f"the reader consumed {self.served} bytes without refusing the line"
            )
        self.served += size
        return "a" * size


def test_the_reader_refuses_before_it_has_buffered_a_whole_line():
    """`MAX_RPC_LINE_BYTES` bounds the sidecar's memory, not just its answers.

    Iterating `sys.stdin` line by line checks the size only once the line is already in
    memory, which is the one place the bound had to hold and did not.
    """
    stream = EndlessLine(budget=MAX_RPC_LINE_BYTES * 2)
    assert next(rpc.bounded_lines(stream)) is None
    assert stream.served > MAX_RPC_LINE_BYTES, "the refusal must follow a real overrun"


def test_an_oversized_line_does_not_desynchronise_the_stream(monkeypatch, capsys):
    """Refusing a request must not turn the rest of it into further requests.

    A reader that drops an oversized line without resynchronising to the next newline
    hands its tail to the parser as if it were fresh traffic.
    """
    oversized = '{"jsonrpc":"2.0","id":1,"method":"x","params":"%s"}' % ("a" * MAX_RPC_LINE_BYTES)
    valid = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "engine.capabilities.v1"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(oversized + "\n" + valid + "\n"))

    assert rpc.main() == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 2, "one refusal and one answer, not a refusal and a pile of junk"
    assert json.loads(lines[0])["error"]["message"] == "Request too large"
    assert json.loads(lines[1])["id"] == 2
    assert json.loads(lines[1])["result"]["engine"] == "motor-costos"


def test_a_final_line_without_a_trailing_newline_is_still_answered(monkeypatch, capsys):
    """A parent process that closes the pipe after its last request still gets an answer."""
    request = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "engine.capabilities.v1"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(request))
    assert rpc.main() == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert [json.loads(line)["id"] for line in lines] == [7]


def test_an_unknown_method_without_params_is_still_method_not_found():
    """Regression: judging the parameters before resolving the method sent the caller
    hunting for a bad argument in a call that does not exist."""
    line = '{"jsonrpc":"2.0","id":1,"method":"cost.cascade.v9"}'
    assert json.loads(handle_line(line))["error"]["code"] == METHOD_NOT_FOUND


def test_every_advertised_method_is_dispatchable():
    for method in rpc.METHODS:
        response = json.loads(call(method, {}))
        assert response.get("error", {}).get("code") != METHOD_NOT_FOUND, method


@pytest.mark.parametrize("method", [None, 42, {"a": 1}, ["x"]])
def test_a_request_whose_method_is_missing_or_not_a_string_is_invalid(method):
    request = {"jsonrpc": "2.0", "id": 1}
    if method is not None:
        request["method"] = method
    assert json.loads(handle_line(json.dumps(request)))["error"]["code"] == INVALID_REQUEST
