"""Build 60 clearly simulated restaurant entries and explicit mock annotations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FOOD_GOOD = [
    "The noodles were flavorful", "The dumplings tasted fresh", "The soup was rich",
    "The grilled fish was excellent", "The rice was perfectly cooked", "The dessert was delicate",
    "The curry had great depth", "The bread arrived warm", "The vegetables were crisp",
    "The broth was fragrant", "The tofu was well seasoned", "The pie was delicious",
]
SERVICE_MIXED = [
    ("the server forgot our order", "negative"), ("service was painfully slow", "negative"),
    ("the waiter ignored our table", "negative"), ("staff mixed up the dishes", "negative"),
    ("we waited too long for water", "negative"), ("the cashier was rude", "negative"),
    ("the server was attentive", "positive"), ("staff welcomed us warmly", "positive"),
    ("our waiter was helpful", "positive"), ("service was quick", "positive"),
    ("the host was considerate", "positive"), ("staff handled requests promptly", "positive"),
]
SERVICE_ONLY = [
    ("Our server forgot the drinks", "negative"), ("The staff left us waiting at the entrance", "negative"),
    ("The waiter spoke sharply to us", "negative"), ("Nobody checked on our table", "negative"),
    ("The bill took ages to arrive", "negative"), ("The host lost our reservation", "negative"),
    ("The team greeted us kindly", "positive"), ("Our waiter explained the menu clearly", "positive"),
    ("The staff responded quickly", "positive"), ("The host found us a seat immediately", "positive"),
    ("Service was ordinary", "neutral"), ("The staff interaction was unremarkable", "neutral"),
]
FOOD_PRICE = [
    (("The pasta was bland", "negative"), ("the bill was excessive", "negative")),
    (("The fish was overcooked", "negative"), ("the meal cost too much", "negative")),
    (("The vegetables were soggy", "negative"), ("the prices were steep", "negative")),
    (("The soup arrived cold", "negative"), ("the portions were expensive", "negative")),
    (("The steak lacked flavor", "negative"), ("the menu was overpriced", "negative")),
    (("The rice tasted stale", "negative"), ("the charge felt unreasonable", "negative")),
    (("The salad was refreshing", "positive"), ("the lunch special was pricey", "negative")),
    (("The noodles were satisfying", "positive"), ("the dessert cost too much", "negative")),
    (("The cake tasted wonderful", "positive"), ("the set menu was good value", "positive")),
    (("The seafood was fresh", "positive"), ("the price was fair", "positive")),
    (("The pizza was tasty but the crust was burnt", "conflict"), ("the deal was affordable", "positive")),
    (("The curry was aromatic but too salty", "conflict"), ("the bill was reasonable", "positive")),
]
AMBIENCE = [
    ("The dining room was noisy", "negative"), ("The lights were harsh", "negative"),
    ("The tables felt cramped", "negative"), ("The music was too loud", "negative"),
    ("The room was calm", "positive"), ("The decor was inviting", "positive"),
    ("The terrace was pleasant", "positive"), ("The lighting felt warm", "positive"),
    ("The room looked ordinary", "neutral"), ("The decor was unremarkable", "neutral"),
    ("The room was lively but uncomfortably crowded", "conflict"),
    ("The music was pleasant but too loud", "conflict"),
]
SERVICE_AMBIENCE = [
    ("staff forgot our request", "negative"), ("the waiter delayed our meal", "negative"),
    ("service was inattentive", "negative"), ("the host ignored us", "negative"),
    ("our server was curt", "negative"), ("staff brought the wrong bill", "negative"),
    ("service was attentive", "positive"), ("the waiter checked on us", "positive"),
    ("staff solved a problem quickly", "positive"), ("the host was welcoming", "positive"),
    ("our server was patient", "positive"), ("staff were cheerful", "positive"),
]
MISC = [
    "The booking website was confusing", "Parking nearby was difficult", "The location was hard to find",
    "The queue outside was poorly marked", "The opening hours were unclear", "The phone line kept disconnecting",
    "The online booking was simple", "Parking was convenient", "The location was easy to reach",
    "The waiting area had useful signs", "The hours were clearly posted", "The phone reservation was smooth",
]
SERVICE_MISC = [
    ("the host was dismissive", "negative"), ("staff could not help", "negative"),
    ("the server ignored the issue", "negative"), ("staff were impatient", "negative"),
    ("the waiter offered no explanation", "negative"), ("the host was rude", "negative"),
    ("the host helped immediately", "positive"), ("staff were accommodating", "positive"),
    ("the server answered our questions", "positive"), ("staff stayed helpful", "positive"),
    ("the waiter gave clear directions", "positive"), ("the host was friendly", "positive"),
]


def build_entries() -> list[dict]:
    if any(len(items) != 12 for items in
           [FOOD_GOOD, SERVICE_MIXED, SERVICE_ONLY, FOOD_PRICE, AMBIENCE, SERVICE_AMBIENCE, MISC, SERVICE_MISC]):
        raise ValueError("each synthetic template group must contain 12 entries")
    entries = []

    def append(text: str, *aspects: tuple[str, str, str]) -> None:
        entries.append({"record_id": f"S{len(entries) + 1:02d}", "text": text,
                        "aspects": [{"category": category, "sentiment": sentiment, "evidence": [span]}
                                    for category, sentiment, span in aspects]})

    for food, (service, label) in zip(FOOD_GOOD, SERVICE_MIXED):
        connector = "but" if label == "negative" else "and"
        append(f"{food}, {connector} {service}.", ("food", "positive", food), ("service", label, service))
    for service, label in SERVICE_ONLY:
        append(f"{service}.", ("service", label, service))
    for (food, food_label), (price, price_label) in FOOD_PRICE:
        append(f"{food}, and {price}.", ("food", food_label, food), ("price", price_label, price))
    for (ambience, ambience_label), (service, service_label) in zip(AMBIENCE, SERVICE_AMBIENCE):
        append(f"{ambience}, and {service}.", ("ambience", ambience_label, ambience), ("service", service_label, service))
    for index, (misc, (service, service_label)) in enumerate(zip(MISC, SERVICE_MISC)):
        append(f"{misc}, and {service}.", ("anecdotes/miscellaneous", "negative" if index < 6 else "positive", misc),
               ("service", service_label, service))
    if len(entries) != 60 or len({item["text"] for item in entries}) != 60:
        raise ValueError("presentation fixture must contain 60 unique entries")
    return entries


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-out", default="data/demo/presentation.csv")
    parser.add_argument("--annotations-out", default="data/demo/presentation_annotations.json")
    args = parser.parse_args(argv)
    entries = build_entries()
    csv_path = Path(args.csv_out)
    annotations_path = Path(args.annotations_out)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    annotations_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_id", "text"])
        writer.writeheader()
        writer.writerows({"record_id": item["record_id"], "text": item["text"]} for item in entries)
    annotations_path.write_text(json.dumps({"provenance": "SIMULATED_MOCK_FIXTURE", "records": entries}, indent=2), encoding="utf-8")
    print(json.dumps({"mode": "SIMULATED_MOCK_FIXTURE", "records": len(entries)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
