"""Read-only DeepSeek balance gate for bounded development runs.

CNY / 10 is a deliberately conservative safety allowance in USD units, not
an exchange-rate quote. At most half of that allowance may be reserved for a
new run. The provider bill remains authoritative.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_BALANCE_URL = "https://api.deepseek.com/user/balance"
_MAX_BALANCE_BYTES = 16 * 1024
_CNY_SAFETY_DIVISOR = Decimal(10)
_RESERVE_MULTIPLE = Decimal(2)


class BalanceError(RuntimeError):
    """Sanitized balance or transport failure."""


def _fetch_balance(api_key: str) -> dict[str, Any]:
    request = Request(_BALANCE_URL, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(_MAX_BALANCE_BYTES + 1)
    except HTTPError as exc:
        raise BalanceError(f"balance endpoint HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise BalanceError("balance endpoint unavailable") from None
    if len(raw) > _MAX_BALANCE_BYTES:
        raise BalanceError("balance response too large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BalanceError("balance response invalid") from None
    if not isinstance(value, dict):
        raise BalanceError("balance response invalid")
    return value


def _nonnegative_decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BalanceError("balance amount invalid") from None
    if not number.is_finite() or number < 0:
        raise BalanceError("balance amount invalid")
    return number


def available_dev_run_cap_usd(*, api_key: str | None = None,
                              fetch_balance: Callable[[str], dict[str, Any]] = _fetch_balance) -> Decimal:
    """Return a conservative maximum cap for one new run; no model call."""
    key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY")
    if not key or "\r" in key or "\n" in key:
        raise BalanceError("DEEPSEEK_API_KEY unavailable")
    try:
        value = fetch_balance(key)
    except BalanceError:
        raise
    except Exception:
        raise BalanceError("balance endpoint unavailable") from None
    if not isinstance(value, dict) or value.get("is_available") is not True:
        raise BalanceError("DeepSeek balance unavailable for model calls")
    infos = value.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise BalanceError("balance response invalid")
    safe_usd = Decimal(0)
    for item in infos:
        if not isinstance(item, dict):
            raise BalanceError("balance response invalid")
        currency = item.get("currency")
        amount = _nonnegative_decimal(item.get("total_balance"))
        if currency == "USD":
            safe_usd += amount
        elif currency == "CNY":
            safe_usd += amount / _CNY_SAFETY_DIVISOR
        else:
            raise BalanceError("balance currency unsupported")
    return safe_usd / _RESERVE_MULTIPLE


def require_dev_run_balance(max_cost_usd: object, *, api_key: str | None = None,
                            fetch_balance: Callable[[str], dict[str, Any]] = _fetch_balance) -> None:
    """Fail closed before starting a bounded DeepSeek development run."""
    try:
        cap = Decimal(str(max_cost_usd))
    except (InvalidOperation, ValueError):
        raise ValueError("positive finite run cap required") from None
    if not cap.is_finite() or cap <= 0:
        raise ValueError("positive finite run cap required")
    if available_dev_run_cap_usd(api_key=api_key, fetch_balance=fetch_balance) < cap:
        raise BalanceError("DeepSeek balance below conservative run reserve")


def require_formal_run_balance(worst_case_usd: object, *, api_key: str | None = None,
                               fetch_balance: Callable[[str], dict[str, Any]] = _fetch_balance) -> None:
    """Require the declared worst-case spend without the development-only reserve.

    The same read-only provider check and conservative CNY conversion still apply.
    Request, token and local spend caps remain enforced by the formal runner.
    """
    try:
        required = Decimal(str(worst_case_usd))
    except (InvalidOperation, ValueError):
        raise ValueError("positive finite formal worst-case amount required") from None
    if not required.is_finite() or required <= 0:
        raise ValueError("positive finite formal worst-case amount required")
    available = available_dev_run_cap_usd(api_key=api_key, fetch_balance=fetch_balance)
    if available * _RESERVE_MULTIPLE < required:
        raise BalanceError("DeepSeek balance below declared formal worst case")
