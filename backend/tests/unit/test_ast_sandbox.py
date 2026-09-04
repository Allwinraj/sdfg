from __future__ import annotations

from decimal import Decimal

import pytest

from app.engine.ast_sandbox import SandboxError, eval_expr


def test_arithmetic_and_compare() -> None:
    assert eval_expr("a + b > 10", {"a": 6, "b": 5}) is True
    assert eval_expr("min(a, b)", {"a": 3, "b": 9}) == 3
    assert eval_expr("amount > 0 and status == 'open'", {"amount": 1, "status": "open"}) is True


def test_decimal_not_float_drift() -> None:
    result = eval_expr("0.1 + 0.2")
    assert result == Decimal("0.3")


def test_rejects_attribute_and_import() -> None:
    with pytest.raises(SandboxError):
        eval_expr("__import__('os').system('x')", {})
    with pytest.raises(SandboxError):
        eval_expr("(a).bit_length()", {"a": 1})


def test_rejects_unknown_call() -> None:
    with pytest.raises(SandboxError):
        eval_expr("eval('1')", {})
