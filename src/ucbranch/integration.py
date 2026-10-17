"""Thin access to pinned generic features and parameter optimizer."""

import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
BRANCHER = ROOT / "third_party/llm4branch/examples/brancher"
sys.path.insert(0, str(BRANCHER))
from utils.utils import normalize, load_program


def parameter_optimizer(execute, *args):
    # Bind the existing optimizer to UC evaluation without altering upstream globals.
    spec = importlib.util.spec_from_file_location(
        "upstream_brancher", BRANCHER / "evaluator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.params_optimizer
    bindings = dict(original.__globals__, execute_ecole=execute)
    adapted = types.FunctionType(original.__code__, bindings, original.__name__)
    return adapted(*args)
