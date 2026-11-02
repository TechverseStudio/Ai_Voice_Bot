import pytest

from backend.outbound import CallRequest, initiate_call, validate_phone_number


def test_validate_phone_number():
    assert validate_phone_number("+919999999999") == "+919999999999"


def test_reject_invalid_phone_number():
    with pytest.raises(ValueError):
        validate_phone_number("not-a-number")


def test_mock_call(monkeypatch):
    monkeypatch.setenv("TELEPHONY_PROVIDER", "mock")
    result = initiate_call(CallRequest("+919999999999", 1))
    assert result.status == "simulated_accepted"
    assert result.provider_call_id.startswith("mock-")
