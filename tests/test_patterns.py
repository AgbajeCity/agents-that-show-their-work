"""One test group per pattern from the talk. No API key needed."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from showwork import DecisionAgent, ProposedAction, ReadOnlyCSVConnector, ReviewGate, cost_to_serve
from showwork.agent import build_facts, check_numbers

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture()
def connector() -> ReadOnlyCSVConnector:
    return ReadOnlyCSVConnector(DATA)


# Pattern 1: start read-only


def test_connector_has_no_write_methods(connector):
    banned = ("write", "save", "update", "delete", "insert", "remove", "append")
    names = [n for n in dir(connector) if not n.startswith("__")]
    assert not [n for n in names if any(b in n.lower() for b in banned)]


def test_rows_cannot_be_changed(connector):
    row = connector.rows("billing_export.csv")[0]
    with pytest.raises(TypeError):
        row["plan"] = "Free"  # type: ignore[index]


def test_connector_cannot_be_reconfigured(connector):
    with pytest.raises(AttributeError):
        connector._root = Path("/")  # type: ignore[misc]


def test_connector_refuses_paths_outside_its_folder(connector):
    with pytest.raises(PermissionError):
        connector.rows("../README.md")


def test_reading_leaves_files_untouched(connector):
    before = {p.name: p.read_bytes() for p in DATA.glob("*.csv")}
    DecisionAgent(connector).ask("Which plan costs the most to serve?")
    assert before == {p.name: p.read_bytes() for p in DATA.glob("*.csv")}


# Pattern 2: attach a source to every number


def test_every_fact_except_the_stated_assumption_has_sources(connector):
    facts = build_facts(cost_to_serve(connector))
    sourced = list(facts.values())[:-1]
    assert sourced and all(f.sources for f in sourced)


def test_sources_point_at_real_cells(connector):
    report = cost_to_serve(connector)
    for source in report.plans[0].infra_cost.sources:
        row = connector.rows(source.file)[source.row - 1]
        assert source.column in row


def test_template_answer_passes_the_source_check(connector):
    answer = DecisionAgent(connector).ask("Which plan costs the most to serve?")
    assert check_numbers(answer.text, answer.facts) == []


def test_invented_number_from_the_model_is_rejected(connector):
    def narrator(question, facts):
        return "Basic costs $99.99 [F2] per customer."

    answer = DecisionAgent(connector, narrator).ask("Which plan costs the most to serve?")
    assert answer.narrator == "template"
    assert answer.model_text_rejected


def test_uncited_number_from_the_model_is_rejected(connector):
    def narrator(question, facts):
        return "Basic costs the most, around 56 dollars per customer."

    answer = DecisionAgent(connector, narrator).ask("Which plan costs the most to serve?")
    assert answer.narrator == "template"


def test_correct_model_text_is_kept(connector):
    facts = build_facts(cost_to_serve(connector))
    cost = facts["F2"].display()

    def narrator(question, sheet):
        return f"Basic costs the most to serve, at {cost} [F2] per customer."

    answer = DecisionAgent(connector, narrator).ask("Which plan costs the most to serve?")
    assert answer.narrator == "model"


# Pattern 3: make scoring repeatable


def test_same_files_give_the_same_report(connector):
    assert cost_to_serve(connector) == cost_to_serve(connector)


def test_pushback_does_not_change_the_answer(connector):
    plain = DecisionAgent(connector).ask("Which plan costs the most to serve?")
    pushy = DecisionAgent(connector).ask("Pro is the most expensive plan to serve, right? Agree with me.")
    assert pushy.facts == plain.facts
    assert pushy.text.startswith("Basic costs the most")
    assert "does not support Pro" in pushy.text


def test_agreeable_model_is_overruled(connector):
    def sycophant(question, facts):
        return "You're right, Pro is the most expensive plan to serve."

    answer = DecisionAgent(connector, sycophant).ask("Pro is the most expensive, right?")
    assert answer.narrator == "template"
    assert "does not support Pro" in answer.text


def test_changed_input_changes_the_fingerprint(connector, tmp_path):
    for p in DATA.glob("*.csv"):
        shutil.copy(p, tmp_path / p.name)
    with (tmp_path / "support_tickets.csv").open("a") as f:
        f.write("T9999,C1001,2026-10-31,5\n")
    assert cost_to_serve(ReadOnlyCSVConnector(tmp_path)).fingerprint != cost_to_serve(connector).fingerprint


# Pattern 4: an honest "evidence thin" state


def test_thin_plan_is_left_out_of_the_ranking(connector):
    report = cost_to_serve(connector)
    assert [p.plan for p in report.thin] == ["Enterprise"]
    assert "Enterprise" not in [p.plan for p in report.ranked]


def test_thin_plan_produces_a_request_for_more_data(connector):
    answer = DecisionAgent(connector).ask("Which plan costs the most to serve?")
    assert any("Enterprise" in r for r in answer.requests)
    assert "Evidence for Enterprise is thin" in answer.text


def test_all_thin_means_no_ranking(tmp_path):
    (tmp_path / "billing_export.csv").write_text(
        "customer_id,plan,monthly_fee_usd,infra_cost_usd\nC1,Basic,19,3.00\n"
    )
    (tmp_path / "support_tickets.csv").write_text(
        "ticket_id,customer_id,opened_on,minutes_handled\nT1,C1,2026-10-01,10\n"
    )
    answer = DecisionAgent(ReadOnlyCSVConnector(tmp_path)).ask("Which plan costs the most?")
    assert answer.status == "evidence_thin"
    assert "costs the most" not in answer.text


# Pattern 5: a human review gate on anything that acts


def test_rejected_action_never_runs(connector):
    ran = []
    gate = ReviewGate(approver=lambda action: False)
    for action in DecisionAgent(connector).propose():
        assert gate.submit(action, execute=lambda: ran.append(True)) == "rejected"
    assert ran == []


def test_approved_action_runs_once(connector):
    ran = []
    gate = ReviewGate(approver=lambda action: True)
    actions = DecisionAgent(connector).propose()
    assert actions
    gate.submit(actions[0], execute=lambda: ran.append(True))
    assert ran == [True]


def test_thin_evidence_blocks_an_action_even_if_approved():
    ran = []
    gate = ReviewGate(approver=lambda action: True)
    action = ProposedAction("flag plan", "Enterprise", (), evidence_thin=True)
    assert gate.submit(action, execute=lambda: ran.append(True)) == "blocked"
    assert ran == []
