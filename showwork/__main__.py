"""Command line entry point.

    python -m showwork ask "Which plan costs the most to serve?"
    python -m showwork ask "Pro is the most expensive plan, right?" --gemini
    python -m showwork sources F2
    python -m showwork propose
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .agent import DecisionAgent, build_facts
from .connectors import ReadOnlyCSVConnector
from .review import ReviewGate
from .scoring import cost_to_serve

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(prog="showwork")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="folder with the CSV files")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="ask which plan costs the most to serve")
    ask.add_argument("question")
    ask.add_argument("--gemini", action="store_true", help="let Gemini write the explanation")

    src = sub.add_parser("sources", help="list every cell behind a fact")
    src.add_argument("fact_id")

    sub.add_parser("propose", help="propose actions and send them through human review")

    args = parser.parse_args()
    connector = ReadOnlyCSVConnector(args.data)

    if args.command == "ask":
        narrator = None
        if args.gemini:
            from .gemini import GeminiNarrator

            narrator = GeminiNarrator()
        answer = DecisionAgent(connector, narrator).ask(args.question)
        print(answer.text)
        for line in answer.requests:
            print(f"Request: {line}")
        print(f"\nStatus: {answer.status}. Written by: {answer.narrator}. "
              f"Input fingerprint: {answer.fingerprint}")
        if answer.model_text_rejected:
            print("The model's draft failed the source check and was replaced:")
            print(f"  {answer.model_text_rejected}")
        print("Run `python -m showwork sources F<n>` to see the cells behind any fact.")

    elif args.command == "sources":
        facts = build_facts(cost_to_serve(connector))
        fact = facts.get(args.fact_id.upper())
        if fact is None:
            parser.error(f"unknown fact {args.fact_id}; facts run from F1 to F{len(facts)}")
        print(f"{args.fact_id.upper()} {fact.label}: {fact.display()}")
        if not fact.sources:
            print("  stated assumption in showwork/scoring.py")
        for source in fact.sources:
            print(f"  {source}")

    elif args.command == "propose":
        gate = ReviewGate()
        actions = DecisionAgent(connector).propose()
        if not actions:
            print("Nothing to propose.")
        for action in actions:
            result = gate.submit(action, execute=lambda a=action: print(f"Flagged: {a.detail}"))
            print(f"Result: {result}")


if __name__ == "__main__":
    main()
