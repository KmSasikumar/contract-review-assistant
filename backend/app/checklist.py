"""The fixed 8-item review checklist (from the task brief)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    label: str
    question: str  # what the reviewer must decide
    keywords: list[str]  # retrieval hints (used for keyword search + prompt)


CHECKLIST: list[ChecklistItem] = [
    ChecklistItem(
        key="parties",
        label="Parties",
        question="Who are the parties to the contract? Give their full legal names.",
        keywords=["parties", "between", "entered into", "agreement", "party"],
    ),
    ChecklistItem(
        key="term",
        label="Start date and term",
        question="When does the contract start and how long does it last?",
        keywords=["term", "commencement", "effective date", "start date", "duration", "expires", "starts on", "continues for"],
    ),
    ChecklistItem(
        key="payment",
        label="Payment terms",
        question="What are the payment terms — how much, when, and how is it paid?",
        keywords=["payment", "fees", "payable", "invoice", "amount", "price", "pay"],
    ),
    ChecklistItem(
        key="termination",
        label="Termination",
        question="How can either side end the contract, and what notice is required?",
        keywords=["termination", "terminate", "notice", "end this agreement"],
    ),
    ChecklistItem(
        key="liability",
        label="Limitation of liability",
        question="Is there a cap or limit on what a party must pay if something goes wrong?",
        keywords=["liability", "limitation of liability", "cap", "damages", "in no event"],
    ),
    ChecklistItem(
        key="confidentiality",
        label="Confidentiality",
        question="Does the contract require the parties to keep shared information private?",
        keywords=["confidential", "confidentiality", "non-disclosure", "proprietary"],
    ),
    ChecklistItem(
        key="governing_law",
        label="Governing law",
        question="Which country's or state's law governs the contract, and where are disputes heard?",
        keywords=["governing law", "governed by", "jurisdiction", "laws of"],
    ),
    ChecklistItem(
        key="auto_renewal",
        label="Auto-renewal",
        question="Does the contract renew automatically, and how can auto-renewal be stopped?",
        keywords=["auto-renew", "automatic renewal", "renew", "renewal"],
    ),
]

BY_KEY = {item.key: item for item in CHECKLIST}

# Risk flags derived from the review verdicts (bonus requirement).
# Each rule: (checklist key, status that triggers it, message).
RISK_RULES = [
    (
        "liability",
        "not_found",
        "No cap on liability — needs attention: a party's exposure is uncapped.",
    ),
    (
        "termination",
        "not_found",
        "No termination clause — needs attention: it may be unclear how to exit.",
    ),
    (
        "auto_renewal",
        "found",
        "Auto-renewal present — check the notice window for stopping it.",
    ),
    (
        "governing_law",
        "not_found",
        "No governing law — needs attention: disputes have no agreed forum.",
    ),
]


def risk_flags(items: dict[str, str]) -> list[str]:
    """items: {checklist key: status}. Returns human-readable risk flags."""
    return [msg for key, status, msg in RISK_RULES if items.get(key) == status]
