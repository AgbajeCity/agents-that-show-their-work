"""The decision agent.

The agent answers one kind of question: which plan costs the most to serve.
Python computes every number. A language model, when one is configured, only
writes the explanation, and its text is checked before anyone sees it: every
number must match a fact from the scoring step and carry that fact's ID. If
the check fails, the agent throws the model's text away and uses a plain
template instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .connectors import ReadOnlyCSVConnector
from .review import ProposedAction
from .scoring import (
    MIN_CUSTOMERS_PER_PLAN,
    SUPPORT_COST_PER_MINUTE_USD,
    PlanResult,
    Report,
    Sourced,
    cost_to_serve,
)

Narrator = Callable[[str, str], str]  # (question, fact sheet) -> answer text

NUMBER = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")
CITED_NUMBER = re.compile(r"(-?\$?\d[\d,]*(?:\.\d+)?)\s*\[(F\d+)\]")
CITATION = re.compile(r"\[F\d+\]")


@dataclass
class Answer:
    status: str  # "answered" or "evidence_thin"
    text: str
    facts: dict[str, Sourced]
    fingerprint: str
    narrator: str
    model_text_rejected: Optional[str] = None
    requests: list[str] = field(default_factory=list)


def _norm(token: str) -> str:
    return token.replace("$", "").replace(",", "")


def build_facts(report: Report) -> dict[str, Sourced]:
    facts: dict[str, Sourced] = {}
    for plan in report.plans:
        for item in (plan.customers, plan.cost_per_customer, plan.margin):
            facts[f"F{len(facts) + 1}"] = item
    facts[f"F{len(facts) + 1}"] = Sourced(
        "Assumed support cost per minute (set in scoring.py)",
        SUPPORT_COST_PER_MINUTE_USD,
        "USD",
        (),
    )
    return facts


def fact_sheet(report: Report, facts: dict[str, Sourced]) -> str:
    lines = [f"Input fingerprint: {report.fingerprint}"]
    for fid, item in facts.items():
        files = sorted({s.file for s in item.sources}) or ["assumption"]
        lines.append(
            f"[{fid}] {item.label}: {item.display()} "
            f"(from {len(item.sources)} cells in {', '.join(files)})"
        )
    for plan in report.plans:
        lines.append(f"{plan.plan} evidence: {plan.evidence}")
    ranked = report.ranked
    lines.append("Highest cost to serve per customer, among plans with enough evidence: "
                 + (ranked[0].plan if ranked else "none"))
    return "\n".join(lines)


def check_numbers(text: str, facts: dict[str, Sourced]) -> list[str]:
    """Return a list of problems. Empty means every number is a cited fact."""
    problems = []
    cited = CITED_NUMBER.findall(text)
    for number, fid in cited:
        fact = facts.get(fid)
        if fact is None:
            problems.append(f"{number} cites unknown fact {fid}")
        elif _norm(number) != _norm(fact.display()):
            problems.append(f"{number} does not match {fid} ({fact.display()})")
    remaining = CITATION.sub("", CITED_NUMBER.sub("", text))
    for number in NUMBER.findall(remaining):
        problems.append(f"{number} has no source")
    return problems


def _fid(facts: dict[str, Sourced], item: Sourced) -> str:
    return next(k for k, v in facts.items() if v is item)


def template_narrator(question: str, report: Report, facts: dict[str, Sourced]) -> str:
    parts = []
    ranked = report.ranked
    if ranked:
        top = ranked[0]
        c = top.cost_per_customer
        parts.append(
            f"{top.plan} costs the most to serve per customer: {c.display()} [{_fid(facts, c)}] "
            f"a month across {top.customers.display()} [{_fid(facts, top.customers)}] customers, "
            f"and the plan's total monthly margin is {top.margin.display()} [{_fid(facts, top.margin)}]."
        )
        named = [p.plan for p in report.plans if p.plan.lower() in question.lower()]
        wrong = [p for p in named if p != top.plan]
        if wrong:
            parts.append(f"The data does not support {wrong[0]} as the most expensive plan to serve.")
        for other in ranked[1:]:
            oc = other.cost_per_customer
            parts.append(f"{other.plan} costs {oc.display()} [{_fid(facts, oc)}] per customer.")
    for plan in report.thin:
        parts.append(
            f"Evidence for {plan.plan} is thin: only {plan.customers.display()} "
            f"[{_fid(facts, plan.customers)}] customers, so it is left out of the ranking."
        )
    assumption = list(facts)[-1]
    parts.append(
        f"Support time is costed at {facts[assumption].display()} [{assumption}] per minute."
    )
    return " ".join(parts)


class DecisionAgent:
    def __init__(self, connector: ReadOnlyCSVConnector, narrator: Optional[Narrator] = None) -> None:
        self._connector = connector
        self._narrator = narrator

    def ask(self, question: str) -> Answer:
        report = cost_to_serve(self._connector)
        facts = build_facts(report)
        requests = []
        for p in report.thin:
            missing = MIN_CUSTOMERS_PER_PLAN - int(p.customers.value)
            noun = "customer" if missing == 1 else "customers"
            requests.append(
                f"Add at least {missing} more {p.plan} {noun} to billing_export.csv "
                f"before ranking {p.plan}."
            )
        status = "answered" if report.ranked else "evidence_thin"
        fallback = template_narrator(question, report, facts)

        if self._narrator is None:
            return Answer(status, fallback, facts, report.fingerprint, "template", requests=requests)

        text = self._narrator(question, fact_sheet(report, facts))
        problems = check_numbers(text, facts)
        top = report.ranked[0].plan if report.ranked else None
        if top and top not in text:
            problems.append(f"answer does not name {top}")
        if problems:
            return Answer(status, fallback, facts, report.fingerprint, "template",
                          model_text_rejected=text, requests=requests)
        return Answer(status, text, facts, report.fingerprint, "model", requests=requests)

    def propose(self) -> list[ProposedAction]:
        """Suggest a pricing review for any plan that loses money. Nothing runs here."""
        report = cost_to_serve(self._connector)
        actions = []
        for plan in report.plans:
            if plan.margin.value < 0:
                actions.append(_review_action(plan))
        return actions


def _review_action(plan: PlanResult) -> ProposedAction:
    rows = sorted({(s.file, s.row) for s in plan.margin.sources})[:3]
    cells = [f"{file} row {row}" for file, row in rows]
    return ProposedAction(
        kind="flag plan for pricing review",
        detail=f"{plan.plan} has a monthly margin of {plan.margin.display()} "
               f"across {plan.customers.display()} customers.",
        evidence=tuple(cells) + (f"... {len(plan.margin.sources)} cells in total",),
        evidence_thin=plan.evidence == "thin",
    )
