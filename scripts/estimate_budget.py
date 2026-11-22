"""Print planning estimate from explicitly supplied model prices and token bounds."""

from __future__ import annotations

import argparse
import json

from eval.budget import PriceAssumptions, estimate_formal_budget


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--price-date", required=True)
    parser.add_argument("--input-usd-per-million", type=float, required=True)
    parser.add_argument("--output-usd-per-million", type=float, required=True)
    parser.add_argument("--input-tokens-upper", type=int, required=True)
    parser.add_argument("--output-tokens-upper", type=int, required=True)
    args = parser.parse_args(argv)
    assumptions = PriceAssumptions(provider_model=args.model, price_source=args.price_source,
                                   price_date=args.price_date,
                                   usd_per_million_input_tokens=args.input_usd_per_million,
                                   usd_per_million_output_tokens=args.output_usd_per_million,
                                   input_tokens_per_request_upper=args.input_tokens_upper,
                                   output_tokens_per_request_upper=args.output_tokens_upper)
    print(json.dumps(estimate_formal_budget(assumptions), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
