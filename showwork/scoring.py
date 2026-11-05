"""Deterministic cost-to-serve scoring.

Pattern 2: attach a source to every number. Each figure is a `Sourced` value
that carries the exact cells it was computed from.

Pattern 3: make scoring repeatable. No model touches the arithmetic. The same
files always give the same report, and the report carries a fingerprint of
the files it used.

Pattern 4: design an honest "evidence thin" state. A plan with too few
customers is marked thin and left out of the ranking.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .connectors import ReadOnlyCSVConnector, Source

BILLING_FILE = "billing_export.csv"
SUPPORT_FILE = "support_tickets.csv"

# Stated assumption, shown in every answer. Change it here, not in a prompt.
SUPPORT_COST_PER_MINUTE_USD = Decimal("0.90")
MIN_CUSTOMERS_PER_PLAN = 5

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Sourced:
    label: str
    value: Decimal
    unit: str
    sources: tuple[Source, ...] = field(repr=False)

    def display(self) -> str:
        if self.unit == "USD":
            sign = "-" if self.value < 0 else ""
            return f"{sign}${abs(self.value):,.2f}"
        return f"{self.value:,}"


@dataclass(frozen=True)
class PlanResult:
    plan: str
    customers: Sourced
    revenue: Sourced
    infra_cost: Sourced
    support_minutes: Sourced
    cost_to_serve: Sourced
    cost_per_customer: Sourced
    margin: Sourced
    evidence: str  # "ok" or "thin"


@dataclass(frozen=True)
class Report:
    fingerprint: str
    plans: tuple[PlanResult, ...]
    unmatched_tickets: tuple[Source, ...]

    @property
    def ranked(self) -> tuple[PlanResult, ...]:
        """Plans with enough evidence, most expensive to serve per customer first."""
        ok = [p for p in self.plans if p.evidence == "ok"]
        return tuple(sorted(ok, key=lambda p: (-p.cost_per_customer.value, p.plan)))

    @property
    def thin(self) -> tuple[PlanResult, ...]:
        return tuple(p for p in self.plans if p.evidence == "thin")


def cost_to_serve(connector: ReadOnlyCSVConnector) -> Report:
    billing = connector.rows(BILLING_FILE)
    tickets = connector.rows(SUPPORT_FILE)

    customer_plan: dict[str, str] = {}
    customer_cells: dict[str, list[Source]] = defaultdict(list)
    by_plan: dict[str, dict[str, list]] = defaultdict(
        lambda: {"customers": [], "fee": [], "infra": [], "minutes": []}
    )

    for row in billing:
        cid = row["customer_id"].value
        plan = row["plan"].value
        customer_plan[cid] = plan
        customer_cells[cid].append(row["customer_id"].source)
        bucket = by_plan[plan]
        bucket["customers"].append(row["plan"].source)
        bucket["fee"].append((Decimal(row["monthly_fee_usd"].value), row["monthly_fee_usd"].source))
        bucket["infra"].append((Decimal(row["infra_cost_usd"].value), row["infra_cost_usd"].source))

    unmatched: list[Source] = []
    for row in tickets:
        cid = row["customer_id"].value
        plan = customer_plan.get(cid)
        if plan is None:
            unmatched.append(row["customer_id"].source)
            continue
        by_plan[plan]["minutes"].append(
            (Decimal(row["minutes_handled"].value), row["minutes_handled"].source)
        )

    results = []
    for plan in sorted(by_plan):
        b = by_plan[plan]
        n = len(b["customers"])
        fee_src = tuple(s for _, s in b["fee"])
        infra_src = tuple(s for _, s in b["infra"])
        min_src = tuple(s for _, s in b["minutes"])

        revenue = money(sum((v for v, _ in b["fee"]), Decimal(0)))
        infra = money(sum((v for v, _ in b["infra"]), Decimal(0)))
        minutes = sum((v for v, _ in b["minutes"]), Decimal(0))
        cost = money(infra + minutes * SUPPORT_COST_PER_MINUTE_USD)

        results.append(
            PlanResult(
                plan=plan,
                customers=Sourced(f"{plan} customers", Decimal(n), "count", tuple(b["customers"])),
                revenue=Sourced(f"{plan} monthly revenue", revenue, "USD", fee_src),
                infra_cost=Sourced(f"{plan} infrastructure cost", infra, "USD", infra_src),
                support_minutes=Sourced(f"{plan} support minutes", minutes, "minutes", min_src),
                cost_to_serve=Sourced(f"{plan} cost to serve", cost, "USD", infra_src + min_src),
                cost_per_customer=Sourced(
                    f"{plan} cost to serve per customer",
                    money(cost / n),
                    "USD",
                    infra_src + min_src + tuple(b["customers"]),
                ),
                margin=Sourced(
                    f"{plan} monthly margin", money(revenue - cost), "USD", fee_src + infra_src + min_src
                ),
                evidence="ok" if n >= MIN_CUSTOMERS_PER_PLAN else "thin",
            )
        )

    return Report(
        fingerprint=connector.fingerprint(BILLING_FILE, SUPPORT_FILE),
        plans=tuple(results),
        unmatched_tickets=tuple(unmatched),
    )
