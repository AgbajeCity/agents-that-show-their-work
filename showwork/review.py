"""Human review before anything acts.

Pattern 5: put a human review gate on anything that acts. The agent can only
propose an action. The action runs after a person approves it, and never when
its evidence is thin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ProposedAction:
    kind: str
    detail: str
    evidence: tuple[str, ...]
    evidence_thin: bool = False


Approver = Callable[[ProposedAction], bool]


def ask_in_terminal(action: ProposedAction) -> bool:
    print(f"\nProposed action: {action.kind}")
    print(f"  {action.detail}")
    for line in action.evidence:
        print(f"  evidence: {line}")
    return input("Approve? Type yes to run it: ").strip().lower() == "yes"


class ReviewGate:
    def __init__(self, approver: Approver = ask_in_terminal) -> None:
        self._approver = approver
        self.log: list[tuple[ProposedAction, str]] = []

    def submit(self, action: ProposedAction, execute: Callable[[], None]) -> str:
        if action.evidence_thin:
            self.log.append((action, "blocked: evidence thin"))
            return "blocked"
        if not self._approver(action):
            self.log.append((action, "rejected by reviewer"))
            return "rejected"
        execute()
        self.log.append((action, "approved and run"))
        return "approved"
