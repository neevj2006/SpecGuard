import pytest

from services.analysis.decompose import decompose


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
