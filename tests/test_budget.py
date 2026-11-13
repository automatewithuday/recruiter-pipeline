import pytest
from jd2candidates.budget import Budget, BudgetExceeded


def test_budget_stops_at_cap():
    b = Budget(1.0)
    b.add(0.6)
    with pytest.raises(BudgetExceeded):
        b.add(0.5)
    assert b.spent == 0.6


def test_budget_allows_exact_cap():
    b = Budget(1.0)
    b.add(1.0)
    assert b.spent == 1.0
