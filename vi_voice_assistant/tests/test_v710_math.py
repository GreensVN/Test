"""Không được trả số đúng cho một PHẦN của biểu thức hoặc trả NaN/complex."""
import math

import executor
import pytest
from intent_model import _safe_eval, parse_math_expression, predict_intent


@pytest.mark.parametrize("text,expected", [
    ("∛27", 3), ("∛-8", -2), ("∛(125)", 5),
    ("√(81)", 9), ("2 ^ -2", 0.25), ("2 ** -2", 0.25),
    ("-(2+3)*4", -20), ("2 * (+3)", 6), ("2*-3", -6),
    ("2 \u00d7 3", 6), ("8 ÷ 2", 4), ("10 \u2212 3", 7),
    ("(((((2+3))))) * 2", 10),
])
def test_valid_arithmetic(text, expected):
    assert parse_math_expression(text)[1] == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "3+4)", "(3+4", "2*(3+4", "2+", "2**", "2*/3", "2(3+4)",
    "sqrt(9)+1", "sqrt(9", "log 100 + 2", "25% của 100 + 20", "căn 9 cộng 1",
    "(-1)^0.5", "1/0", "(999999+2)^64", "2**3**2",
    "9" * 5000 + "+1", "1+" * 300 + "1",
])
def test_invalid_or_unsupported_math_is_not_partially_evaluated(text):
    assert parse_math_expression(text)[1] is None


@pytest.mark.parametrize("expression", [
    "True + 1", "1e309", "1e308 * 10", "(-1)**0.5", "(2**64)**64",
    "(999999+2)**64", "1+" * 300 + "1", "__import__('os')", "'x' * 100",
])
def test_ast_evaluator_rejects_nonreal_unsafe_or_oversized_results(expression):
    with pytest.raises(ValueError):
        _safe_eval(expression)


@pytest.mark.parametrize("text", ["∛27", "∛(125)", "2 \u00d7 3", "8 ÷ 2", "2 ^ -2"])
def test_symbols_survive_prediction_and_entity_extraction(text):
    result = predict_intent(text)
    assert result["intent"] == "calculate"
    assert result["result"] == pytest.approx(parse_math_expression(text)[1])


@pytest.mark.parametrize("value", [float("nan"), math.inf, -math.inf, 1j, True, {}, "42"])
def test_executor_never_announces_invalid_result_as_success(value):
    assert executor.action_calculate("không tính được", {"result": value}) is False


def test_malformed_original_is_not_reparsed_after_syntax_is_stripped():
    class Calculate:
        def predict(self, texts):
            return ["calculate"]

        def predict_proba(self, texts):
            return [[1.0]]

    result = predict_intent("3+4)", Calculate())
    assert result["result"] is None
    assert executor.action_calculate(result["target"], result) is False
