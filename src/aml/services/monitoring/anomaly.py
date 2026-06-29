from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CustomerProfile:
    mean_amount: Decimal
    std_amount: Decimal
    transaction_count_90d: int
    avg_daily_frequency: float
    known_counterparties: set[str]
    known_currencies: set[str]


@dataclass
class AnomalyResult:
    score: float
    factors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# S — Single Responsibility: each scoring dimension is its own class.
# O — Open/Closed: new dimensions are added by creating a new class,
#     not by modifying AnomalyScorer.
# D — Dependency Inversion: AnomalyScorer depends on the ScoringFactor
#     protocol, not on concrete implementations.
# ---------------------------------------------------------------------------


class ScoringFactor(ABC):
    @property
    @abstractmethod
    def weight(self) -> float: ...

    @abstractmethod
    def score(
        self,
        *,
        amount: Decimal,
        currency: str,
        counterparty: str | None,
        profile: CustomerProfile,
    ) -> tuple[float, str | None]: ...


class AmountScoringFactor(ScoringFactor):
    def __init__(self, *, weight: float = 0.50) -> None:
        self._weight = weight

    @property
    def weight(self) -> float:
        return self._weight

    def score(
        self,
        *,
        amount: Decimal,
        currency: str,  # noqa: ARG002
        counterparty: str | None,  # noqa: ARG002
        profile: CustomerProfile,
    ) -> tuple[float, str | None]:
        raw = self._compute(amount, profile)
        if raw > 0:
            return raw, f"Amount {amount} deviates from mean {profile.mean_amount}"
        return 0.0, None

    @staticmethod
    def _compute(amount: Decimal, profile: CustomerProfile) -> float:
        if profile.std_amount == 0:
            if profile.mean_amount == 0:
                return 0.0
            if amount > profile.mean_amount:
                return min(80.0, float(amount / profile.mean_amount) * 10)
            return 0.0
        z = abs(float(amount - profile.mean_amount) / float(profile.std_amount))
        return min(100.0, z * 15.0)


class CounterpartyScoringFactor(ScoringFactor):
    _NEW_COUNTERPARTY_SCORE = 40.0

    def __init__(self, *, weight: float = 0.25) -> None:
        self._weight = weight

    @property
    def weight(self) -> float:
        return self._weight

    def score(
        self,
        *,
        amount: Decimal,  # noqa: ARG002
        currency: str,  # noqa: ARG002
        counterparty: str | None,
        profile: CustomerProfile,
    ) -> tuple[float, str | None]:
        if counterparty and profile.known_counterparties and counterparty not in profile.known_counterparties:
            return self._NEW_COUNTERPARTY_SCORE, f"New counterparty: {counterparty}"
        return 0.0, None


class CurrencyScoringFactor(ScoringFactor):
    _NEW_CURRENCY_SCORE = 35.0

    def __init__(self, *, weight: float = 0.25) -> None:
        self._weight = weight

    @property
    def weight(self) -> float:
        return self._weight

    def score(
        self,
        *,
        amount: Decimal,  # noqa: ARG002
        currency: str,
        counterparty: str | None,  # noqa: ARG002
        profile: CustomerProfile,
    ) -> tuple[float, str | None]:
        if profile.known_currencies and currency not in profile.known_currencies:
            return self._NEW_CURRENCY_SCORE, f"Unusual currency: {currency}"
        return 0.0, None


def _build_default_factors() -> list[ScoringFactor]:
    return [
        AmountScoringFactor(),
        CounterpartyScoringFactor(),
        CurrencyScoringFactor(),
    ]


class AnomalyScorer:
    def __init__(self, *, factors: list[ScoringFactor] | None = None) -> None:
        self._factors = factors if factors is not None else _build_default_factors()

    def score_transaction(
        self,
        *,
        amount: Decimal,
        currency: str,
        counterparty: str | None,
        profile: CustomerProfile,
    ) -> AnomalyResult:
        explanations: list[str] = []
        weighted_sum = 0.0

        for factor in self._factors:
            raw_score, explanation = factor.score(
                amount=amount,
                currency=currency,
                counterparty=counterparty,
                profile=profile,
            )
            weighted_sum += raw_score * factor.weight
            if explanation:
                explanations.append(explanation)

        final = min(max(weighted_sum, 0.0), 100.0)
        return AnomalyResult(score=final, factors=explanations)
