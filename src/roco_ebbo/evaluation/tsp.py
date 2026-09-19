"""Restricted subprocess evaluator for the shared TSP heuristic contract.

This is intentionally a small development sandbox, not a production security
boundary. AST allow-listing plus a spawned process and timeout reduce accidental
damage, but they do not provide container-, VM-, user-, or syscall-level isolation.
Only trusted local/mock candidate code should be evaluated.
"""

from __future__ import annotations

import ast
import math
import multiprocessing as mp
import time
from multiprocessing.process import BaseProcess
from typing import Any

from roco_ebbo.benchmarks import DistanceMatrix, tour_length
from roco_ebbo.core import EvaluationResult

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


class TSPCodeEvaluator:
    """Evaluate ``heuristic(distance_matrix) -> tour`` outside the host process."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and greater than zero")
        self.timeout_seconds = timeout_seconds

    def evaluate(self, code: str, distance_matrix: DistanceMatrix) -> EvaluationResult:
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
            args=(code, distance_matrix, send_connection),
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

        validation_error = _tour_error(value, len(distance_matrix))
        if validation_error is not None:
            return _failure("invalid_tour", validation_error, started)
        score = tour_length(distance_matrix, value)
        if not math.isfinite(score):
            return _failure("invalid_tour", "tour length is not finite", started)
        return EvaluationResult(
            score=score,
            valid=True,
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
    function = functions[0]
    arguments = function.args
    if (
        [argument.arg for argument in arguments.posonlyargs + arguments.args] != ["distance_matrix"]
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
        or arguments.defaults
        or arguments.kw_defaults
        or function.decorator_list
    ):
        raise _CodeValidationError(
            "signature_error",
            "heuristic must have the exact signature heuristic(distance_matrix)",
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


def _execute_candidate(code: str, distance_matrix: DistanceMatrix, connection: Any) -> None:
    """Compile and execute candidate code only in the spawned subprocess."""

    try:
        namespace: dict[str, Any] = {"__builtins__": _ALLOWED_BUILTINS}
        compiled = compile(code, "<candidate>", "exec")
        exec(compiled, namespace, namespace)  # noqa: S102 - isolated child with restricted builtins
        tour = namespace["heuristic"](distance_matrix)
        connection.send(("ok", tour))
    except BaseException as exc:  # child must turn every candidate failure into data
        message = f"{type(exc).__name__}: {exc}"
        try:
            connection.send(("error", message[:2_000]))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


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


def _tour_error(tour: Any, nodes: int) -> str | None:
    if not isinstance(tour, (list, tuple)):
        return "heuristic must return a list or tuple"
    if len(tour) != nodes:
        return f"tour must contain exactly {nodes} nodes"
    if any(type(node) is not int for node in tour):
        return "every tour entry must be an integer node index"
    if sorted(tour) != list(range(nodes)):
        return f"tour must be a permutation of node indices 0 through {nodes - 1}"
    return None


def _failure(error_type: str, message: str, started: float) -> EvaluationResult:
    return EvaluationResult(
        score=None,
        valid=False,
        runtime_seconds=time.perf_counter() - started,
        error_type=error_type,
        error_message=message,
    )
