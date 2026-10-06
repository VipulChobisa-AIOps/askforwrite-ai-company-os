"""Offline source provider used for deterministic development and tests."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SignalBundle:
    company: str
    website: str
    industry: str
    geography: str
    signals: tuple[str, ...]
    public_contact_channel: str | None = None
    do_not_contact: bool = False


class SourceProvider(Protocol):
    data_mode: str

    def search(self, query: str, limit: int = 10) -> list[SignalBundle]:
        """Return source-backed candidates for an objective."""


class OfflineSignalProvider:
    """Synthetic golden fixtures; this provider never accesses the web."""

    data_mode = "offline_synthetic"

    _fixtures = (
        SignalBundle(
            company="Rajasthan AgriLogistics Pvt Ltd",
            website="https://agrilogistics.example.com",
            industry="Agriculture Logistics",
            geography="Rajasthan, India",
            signals=(
                "hiring field supervisors across 12 districts",
                "reviews mention manual attendance problems",
                "announced fleet expansion for farm-gate collection",
            ),
            public_contact_channel="info@agrilogistics.example.com",
        ),
        SignalBundle(
            company="Jaipur Retail Chain",
            website="https://jaipurretail.example.com",
            industry="Retail Distribution",
            geography="Jaipur, India",
            signals=(
                "job posting for field sales force manager",
                "press note on opening 30 new stores",
            ),
            public_contact_channel="contact@jaipurretail.example.com",
        ),
        SignalBundle(
            company="Gujarat Warehousing Co",
            website="https://gjwarehousing.example.com",
            industry="Warehousing",
            geography="Gujarat, India",
            signals=(
                "tender for inventory control modernization",
                "report on stock discrepancy losses",
            ),
            public_contact_channel="ops@gjwarehousing.example.com",
        ),
        SignalBundle(
            company="Blocked ExampleCorp",
            website="https://blocked-example.com",
            industry="Unknown",
            geography="Unknown",
            signals=("previously requested no contact",),
            do_not_contact=True,
        ),
    )

    def search(self, query: str, limit: int = 10) -> list[SignalBundle]:
        del query
        return list(self._fixtures[:limit])