from __future__ import annotations

import pytest
from pydantic import ValidationError

from jawafdehi_agents.models import CIAACaseInput


def test_case_number_is_normalized():
    case_input = CIAACaseInput(case_number=" 081-cr-0046 ")
    assert case_input.case_number == "081-CR-0046"


@pytest.mark.parametrize("case_number", ["081-0046", "case-123", "081_cr_0046"])
def test_invalid_case_number_is_rejected(case_number: str):
    with pytest.raises(ValidationError):
        CIAACaseInput(case_number=case_number)
