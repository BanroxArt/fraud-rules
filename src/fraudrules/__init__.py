"""fraud-rules: a vendor-neutral rule pack for financial fraud patterns.

Each rule is a YAML file checked against a JSON Schema and compiled to SQL, to
Sigma (for log-shaped rules) and to a Python evaluator that defines the
semantics. Engineering checklist, not legal advice.
"""

from __future__ import annotations

from .loader import RuleError, load_pack, load_rule, parse_rule
from .model import Rule
from .pyeval import Hit, evaluate, run
from .sql import compile_pack, compile_rule, transpile

__all__ = [
    "Hit",
    "Rule",
    "RuleError",
    "compile_pack",
    "compile_rule",
    "evaluate",
    "load_pack",
    "load_rule",
    "parse_rule",
    "run",
    "transpile",
]
__version__ = "0.1.0"
