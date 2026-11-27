from decimal import Decimal

import pytest

from src.deepseek_balance import (BalanceError, available_dev_run_cap_usd,
                                  require_dev_run_balance, require_formal_run_balance)


def _fake(currency, total, *, available=True):
    return lambda key: {"is_available": available, "balance_infos": [
        {"currency": currency, "total_balance": total,
         "granted_balance": "0", "topped_up_balance": total}]}


def test_usd_and_conservative_cny_balance_reserve():
    assert available_dev_run_cap_usd(api_key="test-key", fetch_balance=_fake("USD", "4")) == Decimal("2")
    assert available_dev_run_cap_usd(api_key="test-key", fetch_balance=_fake("CNY", "20")) == Decimal("1")
    require_dev_run_balance("1", api_key="test-key", fetch_balance=_fake("CNY", "20"))
    with pytest.raises(BalanceError, match="below conservative"):
        require_dev_run_balance("1", api_key="test-key", fetch_balance=_fake("CNY", "19.99"))


@pytest.mark.parametrize("payload", [
    {"is_available": False, "balance_infos": [{"currency": "USD", "total_balance": "100"}]},
    {"is_available": True, "balance_infos": []},
    {"is_available": True, "balance_infos": [{"currency": "EUR", "total_balance": "100"}]},
    {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "NaN"}]},
    {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "-1"}]},
])
def test_invalid_or_unavailable_balance_fails_closed(payload):
    with pytest.raises(BalanceError):
        require_dev_run_balance("0.01", api_key="test-key", fetch_balance=lambda key: payload)


def test_missing_key_and_transport_failure_fail_closed_without_leak(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(BalanceError, match="unavailable"):
        available_dev_run_cap_usd(fetch_balance=lambda key: {"is_available": True})

    def broken(key):
        raise RuntimeError("SECRET_TOKEN_MUST_NOT_APPEAR")

    with pytest.raises(BalanceError, match="balance endpoint unavailable") as raised:
        require_dev_run_balance("0.01", api_key="test-key", fetch_balance=broken)
    assert "SECRET" not in str(raised.value)


def test_formal_worst_case_gate_keeps_provider_and_currency_checks():
    # Development's extra reserve remains intact; the formal gate uses the
    # preflight's full request/token worst case and the same conservative CNY rule.
    balance = _fake("USD", "2.50")
    with pytest.raises(BalanceError, match="reserve"):
        require_dev_run_balance("3.00", api_key="test-key", fetch_balance=balance)
    require_formal_run_balance("2.4772608", api_key="test-key", fetch_balance=balance)
    with pytest.raises(BalanceError, match="formal worst case"):
        require_formal_run_balance("2.51", api_key="test-key", fetch_balance=balance)
    require_formal_run_balance("2", api_key="test-key", fetch_balance=_fake("CNY", "20"))
    with pytest.raises(BalanceError, match="formal worst case"):
        require_formal_run_balance("2.01", api_key="test-key", fetch_balance=_fake("CNY", "20"))


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "unknown"])
def test_formal_worst_case_gate_rejects_invalid_amount(amount):
    with pytest.raises(ValueError, match="formal worst-case"):
        require_formal_run_balance(amount, api_key="test-key", fetch_balance=_fake("USD", "10"))


def test_formal_worst_case_gate_fails_closed_on_unavailable_account():
    with pytest.raises(BalanceError):
        require_formal_run_balance("1", api_key="test-key",
                                   fetch_balance=_fake("USD", "10", available=False))
