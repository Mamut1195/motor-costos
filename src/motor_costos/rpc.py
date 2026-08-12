"""Bounded newline-delimited JSON-RPC 2.0 sidecar.

One request per line, one response per line. stdout carries the protocol and nothing
else. Requests are size-bounded and parsed strictly: `NaN` and `Infinity` are rejected at
any depth, because a non-finite value must never reach a cost calculation.

Method names are `domain.verb.vN`. Params are validated by the contract models
themselves, so `extra="forbid"` and the float refusal apply on the wire exactly as they
do in-process.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any

from pydantic import ValidationError

from motor_costos import capabilities
from motor_costos.cascade import compute_cascade
from motor_costos.contracts import CostCascadeV1, DimensionCheckV1
from motor_costos.dimensions import check_dimension

#: A request line longer than this is refused without ever being buffered whole.
MAX_RPC_LINE_BYTES = 1_000_000

#: How much the reader takes from the stream at a time. Only the buffering granularity;
#: `MAX_RPC_LINE_BYTES` is what actually bounds the memory.
READ_CHUNK_BYTES = 65_536

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32000


class RpcFault(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def strict_loads(line: str) -> Any:
    return json.loads(line, parse_constant=_reject_constant)


def _valid_request_id(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int)) or value is None


#: Method -> contract model. `engine.capabilities.v1` takes no contract.
METHODS: dict[str, type | None] = {
    "engine.capabilities.v1": None,
    "cost.cascade.v1": CostCascadeV1,
    "dimension.check.v1": DimensionCheckV1,
}


def dispatch(method: str, params: Any) -> Any:
    # The method is resolved before the parameters are judged. Reversing the order makes
    # an unknown method with no params report INVALID_PARAMS, which sends the caller
    # looking for a bad argument in a call that does not exist.
    if method not in METHODS:
        raise RpcFault(METHOD_NOT_FOUND, "Method not found")

    if method == "engine.capabilities.v1":
        if params not in (None, {}):
            raise RpcFault(INVALID_PARAMS, "engine.capabilities.v1 takes no parameters")
        return capabilities().model_dump(mode="json")

    if not isinstance(params, dict):
        raise RpcFault(INVALID_PARAMS, "Parameters must be a JSON object")

    try:
        if method == "cost.cascade.v1":
            return compute_cascade(CostCascadeV1(**params)).model_dump(mode="json")
        return check_dimension(DimensionCheckV1(**params)).model_dump(mode="json")
    except ValidationError as exc:
        # The pydantic message is not forwarded: it can quote caller values verbatim and
        # its wording is not part of any contract. Only the count and the field paths go
        # out, which is enough to locate the problem.
        raise RpcFault(
            INVALID_PARAMS,
            f"Invalid parameters for {method}: "
            f"{len(exc.errors())} problem(s) at "
            + ",".join("/".join(str(part) for part in err["loc"]) for err in exc.errors()),
        ) from None


def handle_line(line: str) -> str | None:
    """Handle one request line. Returns the response line, or None for a notification."""
    if len(line.encode("utf-8")) > MAX_RPC_LINE_BYTES:
        return _error_response(None, INVALID_REQUEST, "Request too large")

    try:
        request = strict_loads(line)
    except (ValueError, TypeError):
        return _error_response(None, PARSE_ERROR, "Parse error")

    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error_response(None, INVALID_REQUEST, "Invalid request")

    method = request.get("method")
    if not isinstance(method, str):
        return _error_response(None, INVALID_REQUEST, "Invalid request")

    has_id = "id" in request
    request_id = request.get("id")
    if has_id and not _valid_request_id(request_id):
        return _error_response(None, INVALID_REQUEST, "Invalid request id")

    try:
        result = dispatch(method, request.get("params"))
    except RpcFault as fault:
        return None if not has_id else _error_response(request_id, fault.code, fault.message)
    except Exception:  # noqa: BLE001 - never leak a third-party traceback to the caller
        return None if not has_id else _error_response(request_id, INTERNAL_ERROR, "Internal error")

    if not has_id:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, sort_keys=True)


def _error_response(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        sort_keys=True,
    )


def bounded_lines(stream: Any) -> Iterator[str | None]:
    """Yield one request line at a time, never holding more than the limit.

    `for line in stream` cannot do this. It assembles a whole line before anything can
    judge its size, so `MAX_RPC_LINE_BYTES` would bound only the answers, not the memory
    -- and a peer that never sends a newline decides how much of it to take.

    An overrun yields `None` once, meaning "refuse this line". The remainder is then
    discarded up to the next newline: a reader that dropped the buffer without
    resynchronising would hand the tail of the oversized request to the parser as if it
    were fresh traffic.
    """
    buffer = ""
    discarding = False
    while chunk := stream.read(READ_CHUNK_BYTES):
        buffer += chunk
        while "\n" in buffer:
            line, _, buffer = buffer.partition("\n")
            if discarding:
                discarding = False  # that was the tail of the refused line
            else:
                yield line
        if not discarding and len(buffer.encode("utf-8")) > MAX_RPC_LINE_BYTES:
            buffer = ""
            discarding = True
            yield None
    if buffer and not discarding:
        yield buffer


def main() -> int:
    for line in bounded_lines(sys.stdin):
        if line is None:
            sys.stdout.write(_error_response(None, INVALID_REQUEST, "Request too large") + "\n")
            sys.stdout.flush()
            continue
        line = line.strip()
        if not line:
            continue
        response = handle_line(line)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
