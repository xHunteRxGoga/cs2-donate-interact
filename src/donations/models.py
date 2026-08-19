from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Donation:
    username: str
    amount: float
    currency: str
    message: str = ""
    source: str = "manual"
    donation_id: str = ""
    is_test: bool = False
