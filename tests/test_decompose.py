import pytest

from services.analysis.decompose import Decomposition, RuleDecomposer, decompose


def test_wrapped_criterion_keeps_its_constraints():
    result = decompose(
        "Checkout\n1. Apply the discount\n   only when the customer is eligible.\n"
        "2. Reject expired coupons."
    )
    assert result[0].text == "Apply the discount\n   only when the customer is eligible."
    assert result[0].source_text == result[0].text
    assert len(result) == 2


def test_nested_list_stays_with_parent_criterion():
    result = decompose(
        "- Validate payment:\n  - currency is supported\n  - amount is positive\n- Save receipt"
    )
    assert len(result) == 2
    assert "currency is supported" in result[0].text
    assert "amount is positive" in result[0].text


def test_task_list_markers_are_not_requirement_text():
    result = decompose("- [ ] Reject expired coupons\n- [x] Preserve the total")
    assert [item.text for item in result] == ["Reject expired coupons", "Preserve the total"]


def test_unmarked_trailing_constraint_is_not_discarded():
    result = decompose("- Return the receipt\nNever include payment credentials.")
    assert "Never include payment credentials." in result[0].source_text


@pytest.mark.parametrize("text", ["- [ ] ", "1. \n2. Valid criterion"])
def test_empty_explicit_criterion_is_rejected(text):
    with pytest.raises(ValueError):
        decompose(text)


def test_introductory_constraints_are_available_for_review():
    result = RuleDecomposer().decompose("For authenticated customers only:\n- Save the receipt")
    assert result.context == "For authenticated customers only:"
    assert len(result.criteria) == 1
    assert "introductory context" in result.questions[0]
    assert result.assumptions == []
    assert Decomposition.model_validate_json(result.model_dump_json()) == result


def test_review_questions_identify_duplicates_and_nested_conditions():
    result = RuleDecomposer().decompose("- Save receipt\n- SAVE receipt\n- Validate:\n  - amount")
    assert any("Criterion 2 repeats" in question for question in result.questions)
    assert any("Criterion 3 contains nested" in question for question in result.questions)
    assert len(result.criteria) == 3


def test_prose_requests_review_without_inventing_a_split():
    result = RuleDecomposer().decompose("Save receipts and notify customers.")
    assert result.context == ""
    assert len(result.criteria) == 1
    assert "independently testable" in result.questions[0]
    assert RuleDecomposer().decompose("- Save receipt\n- Notify customer").questions == []
