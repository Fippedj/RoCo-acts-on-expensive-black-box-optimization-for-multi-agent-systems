"""Spawned evaluator for the versioned FSU 01 Multiple Knapsack contract.

The sandbox has the same deliberately limited development-only boundary as the
TSP evaluator.  It is suitable only for trusted local/Mock candidate code.
"""

from __future__ import annotations

import ast
import math
import multiprocessing as mp
import time
from dataclasses import dataclass
from multiprocessing.process import BaseProcess
from typing import Any

from roco_ebbo.benchmarks.mkp import MKPInstance

_ALLOWED_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UAdd,
    ast.USub,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)
_ALLOWED_BUILTINS = {
    "abs": abs,
    "enumerate": enumerate,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "sorted": sorted,
    "sum": sum,
    "tuple": tuple,
}
_ALLOWED_METHODS = {"append", "pop", "remove", "reverse"}
_MAX_CODE_CHARACTERS = 20_000
_MAX_AST_NODES = 2_000


class _CodeValidationError(ValueError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True, slots=True)
class MKPEvaluationResult:
    """Candidate result with source-objective and normalized audit values."""

    score: float | None
    raw_profit: int | None
    normalized_score: float | None
    valid: bool
    feasible: bool
    runtime_seconds: float
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "raw_profit": self.raw_profit,
            "normalized_score": self.normalized_score,
            "normalization_contract": "negative-profit-over-total-positive-profit-v1",
            "valid": self.valid,
            "feasible": self.feasible,
            "runtime_seconds": self.runtime_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class MKPCodeEvaluator:
    """Evaluate ``heuristic(capacities, weights, profits) -> bags``.

    ``bags`` contains one item-index list per knapsack.  Omitted item indices are
    unselected.  Duplicate indices are invalid, including duplicates inside one
    bag.  The shared evolution runtime remains minimize-only, so the only
    selection score is ``-raw_profit``.
    """

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        self.timeout_seconds = timeout_seconds

    def evaluate(self, code: str, instance: MKPInstance) -> MKPEvaluationResult:
        started = time.perf_counter()
        try:
            _validate_source(code)
        except SyntaxError as exc:
            return _failure("syntax_error", str(exc), started)
        except _CodeValidationError as exc:
            return _failure(exc.error_type, str(exc), started)

        context = mp.get_context("spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_execute_candidate,
            args=(
                code,
                instance.capacities,
                instance.weights,
                instance.profits,
                send_connection,
            ),
            daemon=True,
        )
        try:
            process.start()
            send_connection.close()
            payload = _receive_until_exit(
                process,
                receive_connection,
                deadline=time.perf_counter() + self.timeout_seconds,
            )
            if payload is None and process.is_alive():
                _terminate(process)
                return _failure(
                    "timeout",
                    f"candidate exceeded {self.timeout_seconds:g} seconds",
                    started,
                )
            process.join(timeout=0.2)
            if payload is None:
                return _failure(
                    "runtime_error",
                    f"candidate process exited with code {process.exitcode} without a result",
                    started,
                )
        except (OSError, EOFError) as exc:
            if process.is_alive():
                _terminate(process)
            return _failure("runtime_error", f"subprocess failure: {exc}", started)
        finally:
            receive_connection.close()
            if process.is_alive():
                _terminate(process)

        status, value = payload
        if status == "error":
            return _failure("runtime_error", str(value), started)
        error_type, error_message, raw_profit = _validate_assignment(
            value,
            instance.capacities,
            instance.weights,
            instance.profits,
        )
        if error_type is not None:
            assert error_message is not None
            return _failure(error_type, error_message, started)
        assert raw_profit is not None
        try:
            score = float(-raw_profit)
            denominator = max(1, sum(max(0, profit) for profit in instance.profits))
            normalized_score = score / denominator
        except OverflowError:
            return _failure("non_finite_result", "profit cannot be represented as a score", started)
        if not math.isfinite(score) or not math.isfinite(normalized_score):
            return _failure("non_finite_result", "score is not finite", started)
        return MKPEvaluationResult(
            score=score,
            raw_profit=raw_profit,
            normalized_score=normalized_score,
            valid=True,
            feasible=True,
            runtime_seconds=time.perf_counter() - started,
        )


def _validate_source(code: str) -> None:
    if not code.strip():
        raise _CodeValidationError("signature_error", "candidate code is empty")
    if len(code) > _MAX_CODE_CHARACTERS:
        raise _CodeValidationError("unsafe_code", "candidate code exceeds the sandbox size limit")
    tree = ast.parse(code, mode="exec")
    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        raise _CodeValidationError("unsafe_code", "candidate AST exceeds the sandbox node limit")
    for node in nodes:
        if not isinstance(node, _ALLOWED_NODES):
            raise _CodeValidationError(
                "unsafe_code",
                f"AST node {type(node).__name__} is not allowed in the development sandbox",
            )
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise _CodeValidationError("unsafe_code", "private/dunder names are not allowed")
        if isinstance(node, ast.Attribute):
            if node.attr not in _ALLOWED_METHODS or node.attr.startswith("_"):
                raise _CodeValidationError("unsafe_code", f"attribute {node.attr!r} is not allowed")
        if isinstance(node, ast.Call):
            _validate_call(node)

    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(tree.body) != 1 or len(functions) != 1 or functions[0].name != "heuristic":
        raise _CodeValidationError(
            "signature_error",
            "code must contain exactly one top-level function named heuristic",
        )
    arguments = functions[0].args
    actual = [argument.arg for argument in arguments.posonlyargs + arguments.args]
    if (
        actual != ["capacities", "weights", "profits"]
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
        or arguments.defaults
        or arguments.kw_defaults
        or functions[0].decorator_list
    ):
        raise _CodeValidationError(
            "signature_error",
            "heuristic must have the exact signature heuristic(capacities, weights, profits)",
        )


def _validate_call(node: ast.Call) -> None:
    if node.keywords:
        raise _CodeValidationError("unsafe_code", "keyword arguments are not supported")
    if isinstance(node.func, ast.Name):
        if node.func.id not in _ALLOWED_BUILTINS:
            raise _CodeValidationError("unsafe_code", f"call to {node.func.id!r} is not allowed")
        return
    if isinstance(node.func, ast.Attribute) and node.func.attr in _ALLOWED_METHODS:
        return
    raise _CodeValidationError("unsafe_code", "only approved builtins/list methods may be called")


def _execute_candidate(
    code: str,
    capacities: tuple[int, ...],
    weights: tuple[int, ...],
    profits: tuple[int, ...],
    connection: Any,
) -> None:
    try:
        namespace: dict[str, Any] = {"__builtins__": _ALLOWED_BUILTINS}
        compiled = compile(code, "<candidate>", "exec")
        exec(compiled, namespace, namespace)  # noqa: S102 - restricted spawned child
        assignment = namespace["heuristic"](capacities, weights, profits)
        connection.send(("ok", assignment))
    except BaseException as exc:
        message = f"{type(exc).__name__}: {exc}"
        try:
            connection.send(("error", message[:2_000]))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _validate_assignment(
    assignment: Any,
    capacities: tuple[int, ...],
    weights: tuple[int, ...],
    profits: tuple[int, ...],
) -> tuple[str | None, str | None, int | None]:
    if not isinstance(assignment, (list, tuple)):
        return "invalid_assignment", "heuristic must return one list per knapsack", None
    if len(assignment) != len(capacities):
        return (
            "invalid_assignment",
            f"assignment must contain exactly {len(capacities)} knapsack lists",
            None,
        )
    selected: set[int] = set()
    raw_profit = 0
    for knapsack, items in enumerate(assignment):
        if not isinstance(items, (list, tuple)):
            return "invalid_assignment", "each knapsack assignment must be a list or tuple", None
        used_weight = 0
        for item in items:
            if type(item) is not int or item < 0 or item >= len(weights):
                return "invalid_assignment", "item indices must be in the frozen item range", None
            if item in selected:
                return (
                    "duplicate_assignment",
                    "an item may be assigned to at most one knapsack",
                    None,
                )
            selected.add(item)
            used_weight += weights[item]
            raw_profit += profits[item]
        if used_weight > capacities[knapsack]:
            return (
                "capacity_exceeded",
                f"knapsack {knapsack} exceeds its capacity",
                None,
            )
    return None, None, raw_profit


def _receive_until_exit(
    process: BaseProcess,
    connection: Any,
    deadline: float,
) -> tuple[str, Any] | None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None
        if connection.poll(min(0.02, remaining)):
            return connection.recv()
        if not process.is_alive():
            if connection.poll():
                return connection.recv()
            return None


def _terminate(process: BaseProcess) -> None:
    process.terminate()
    process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)


def _failure(error_type: str, message: str, started: float) -> MKPEvaluationResult:
    return MKPEvaluationResult(
        score=None,
        raw_profit=None,
        normalized_score=None,
        valid=False,
        feasible=False,
        runtime_seconds=time.perf_counter() - started,
        error_type=error_type,
        error_message=message,
    )
