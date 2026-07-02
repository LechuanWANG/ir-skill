#!/usr/bin/env python3
"""Mechanical financial checks used by local-investment-research."""

from __future__ import annotations

import argparse
import json
from typing import Sequence


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def verify_market_cap(
    *,
    price: float,
    shares: float,
    reported_market_cap: float,
    tolerance: float = 0.01,
    warn_tolerance: float = 0.05,
    currency: str | None = None,
) -> dict[str, float | str | None]:
    computed = float(price) * float(shares)
    diff_ratio = abs(computed - float(reported_market_cap)) / computed if computed else float("inf")
    if diff_ratio <= tolerance:
        status = "pass"
    elif diff_ratio <= warn_tolerance:
        status = "warn"
    else:
        status = "fail"
    return {
        "status": status,
        "computed_market_cap": computed,
        "reported_market_cap": float(reported_market_cap),
        "difference_ratio": diff_ratio,
        "currency": currency,
    }


def valuation_metrics(
    *,
    price: float,
    eps: float | None = None,
    bvps: float | None = None,
    fcf_per_share: float | None = None,
    dividend: float | None = None,
) -> dict[str, float | None]:
    return {
        "pe": _safe_divide(price, eps),
        "pb": _safe_divide(price, bvps),
        "fcf_yield": _safe_divide(fcf_per_share, price),
        "dividend_yield": _safe_divide(dividend, price),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run mechanical financial checks.")
    sub = parser.add_subparsers(dest="command", required=True)

    market_cap = sub.add_parser("verify-market-cap")
    market_cap.add_argument("--price", type=float, required=True)
    market_cap.add_argument("--shares", type=float, required=True)
    market_cap.add_argument("--reported", type=float, required=True)
    market_cap.add_argument("--currency")

    valuation = sub.add_parser("verify-valuation")
    valuation.add_argument("--price", type=float, required=True)
    valuation.add_argument("--eps", type=float)
    valuation.add_argument("--bvps", type=float)
    valuation.add_argument("--fcf-per-share", type=float)
    valuation.add_argument("--dividend", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-market-cap":
        result = verify_market_cap(
            price=args.price,
            shares=args.shares,
            reported_market_cap=args.reported,
            currency=args.currency,
        )
    else:
        result = valuation_metrics(
            price=args.price,
            eps=args.eps,
            bvps=args.bvps,
            fcf_per_share=args.fcf_per_share,
            dividend=args.dividend,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
