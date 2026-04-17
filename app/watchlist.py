"""Watchlist utilities for default + user-defined tickers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_TICKERS = [
    "AAPL", "TSLA", "NVDA", "AMZN", "MSFT",
    "GOOG", "META", "AMD", "GME", "NKE",
]

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


def normalize_ticker(raw: str) -> str:
    symbol = raw.strip().upper()
    if not symbol:
        raise ValueError("Ticker cannot be empty")
    if not TICKER_PATTERN.fullmatch(symbol):
        raise ValueError(
            "Invalid ticker format. Allowed: letters/numbers plus '.' or '-' (max 10 chars)."
        )
    return symbol


def _watchlist_file() -> Path:
    configured = os.getenv("WATCHLIST_FILE", "app/data/user_tickers.json")
    path = Path(configured)
    if path.is_absolute():
        return path

    project_root = Path(__file__).resolve().parents[1]
    return project_root / path


def _parse_extra_tickers() -> list[str]:
    raw = os.getenv("EXTRA_WATCHED_TICKERS", "").strip()
    if not raw:
        return []

    extras: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            extras.append(normalize_ticker(token))
        except ValueError:
            # Skip invalid env symbols so one typo does not break startup.
            continue
    return extras


def _dedupe_ordered(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def load_user_tickers() -> list[str]:
    path = _watchlist_file()
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    raw_tickers = payload.get("tickers", []) if isinstance(payload, dict) else []
    out: list[str] = []
    for value in raw_tickers:
        if not isinstance(value, str):
            continue
        try:
            out.append(normalize_ticker(value))
        except ValueError:
            continue

    return _dedupe_ordered(out)


def save_user_tickers(tickers: list[str]) -> list[str]:
    normalized = _dedupe_ordered([normalize_ticker(t) for t in tickers])
    path = _watchlist_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tickers": normalized}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return normalized


def add_user_ticker(ticker: str) -> list[str]:
    symbol = normalize_ticker(ticker)
    existing = load_user_tickers()
    if symbol in existing:
        return existing
    existing.append(symbol)
    return save_user_tickers(existing)


def remove_user_ticker(ticker: str) -> list[str]:
    symbol = normalize_ticker(ticker)
    existing = [t for t in load_user_tickers() if t != symbol]
    return save_user_tickers(existing)


def get_effective_tickers() -> list[str]:
    combined = DEFAULT_TICKERS + _parse_extra_tickers() + load_user_tickers()
    return _dedupe_ordered(combined)


def get_watchlist_details() -> dict[str, object]:
    default_tickers = _dedupe_ordered([normalize_ticker(t) for t in DEFAULT_TICKERS])
    extra_tickers = _parse_extra_tickers()
    user_tickers = load_user_tickers()
    effective = _dedupe_ordered(default_tickers + extra_tickers + user_tickers)
    return {
        "watchlist_file": str(_watchlist_file()),
        "default_tickers": default_tickers,
        "extra_tickers": extra_tickers,
        "user_tickers": user_tickers,
        "effective_tickers": effective,
    }
