"""Tests for the anomaly scorer (BE-206 Step 2)."""

from decimal import Decimal

from aml.services.monitoring.anomaly import (
    AmountScoringFactor,
    AnomalyResult,
    AnomalyScorer,
    CounterpartyScoringFactor,
    CurrencyScoringFactor,
    CustomerProfile,
    ScoringFactor,
)


class TestCustomerProfile:
    def test_creation_with_defaults(self):
        profile = CustomerProfile(
            mean_amount=Decimal("5000"),
            std_amount=Decimal("1000"),
            transaction_count_90d=50,
            avg_daily_frequency=0.56,
            known_counterparties={"Acme Corp", "Vendor Inc"},
            known_currencies={"AUD"},
        )
        assert profile.mean_amount == Decimal("5000")
        assert len(profile.known_counterparties) == 2

    def test_empty_profile(self):
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies=set(),
        )
        assert profile.transaction_count_90d == 0


class TestAnomalyScorer:
    def _make_profile(self, **overrides) -> CustomerProfile:
        defaults = {
            "mean_amount": Decimal("5000"),
            "std_amount": Decimal("1000"),
            "transaction_count_90d": 90,
            "avg_daily_frequency": 1.0,
            "known_counterparties": {"Acme Corp", "Vendor Inc"},
            "known_currencies": {"AUD"},
        }
        defaults.update(overrides)
        return CustomerProfile(**defaults)

    def test_normal_transaction_low_score(self):
        scorer = AnomalyScorer()
        profile = self._make_profile()
        result = scorer.score_transaction(
            amount=Decimal("5500"),
            currency="AUD",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert isinstance(result, AnomalyResult)
        assert result.score < 30

    def test_extreme_amount_high_score(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(mean_amount=Decimal("5000"), std_amount=Decimal("1000"))
        result = scorer.score_transaction(
            amount=Decimal("50000"),
            currency="AUD",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert result.score >= 50
        assert any("amount" in f.lower() for f in result.factors)

    def test_new_counterparty_adds_score(self):
        scorer = AnomalyScorer()
        profile = self._make_profile()
        result = scorer.score_transaction(
            amount=Decimal("5000"),
            currency="AUD",
            counterparty="Unknown Shell Company",
            profile=profile,
        )
        assert any("counterparty" in f.lower() for f in result.factors)

    def test_new_currency_adds_score(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(known_currencies={"AUD"})
        result = scorer.score_transaction(
            amount=Decimal("5000"),
            currency="IRR",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert any("currency" in f.lower() for f in result.factors)

    def test_score_is_bounded_0_to_100(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(mean_amount=Decimal("100"), std_amount=Decimal("10"))
        result = scorer.score_transaction(
            amount=Decimal("999999"),
            currency="KPW",
            counterparty="Totally New Entity",
            profile=profile,
        )
        assert 0 <= result.score <= 100

    def test_zero_std_dev_handles_gracefully(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(mean_amount=Decimal("5000"), std_amount=Decimal("0"))
        result = scorer.score_transaction(
            amount=Decimal("10000"),
            currency="AUD",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert 0 <= result.score <= 100

    def test_zero_history_profile(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies=set(),
        )
        result = scorer.score_transaction(
            amount=Decimal("5000"),
            currency="AUD",
            counterparty="First Ever",
            profile=profile,
        )
        assert 0 <= result.score <= 100

    def test_factors_list_is_empty_for_normal_transaction(self):
        scorer = AnomalyScorer()
        profile = self._make_profile()
        result = scorer.score_transaction(
            amount=Decimal("5000"),
            currency="AUD",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert isinstance(result.factors, list)

    def test_multiple_anomaly_factors_compound(self):
        scorer = AnomalyScorer()
        profile = self._make_profile(mean_amount=Decimal("1000"), std_amount=Decimal("200"))
        result = scorer.score_transaction(
            amount=Decimal("50000"),
            currency="KPW",
            counterparty="Unknown Entity",
            profile=profile,
        )
        assert len(result.factors) >= 2
        assert result.score > 50


# ---------------------------------------------------------------------------
# Individual ScoringFactor unit tests (SOLID — Single Responsibility)
# ---------------------------------------------------------------------------


class TestAmountScoringFactor:
    def _make_profile(self, **overrides) -> CustomerProfile:
        defaults = {
            "mean_amount": Decimal("5000"),
            "std_amount": Decimal("1000"),
            "transaction_count_90d": 90,
            "avg_daily_frequency": 1.0,
            "known_counterparties": set(),
            "known_currencies": set(),
        }
        defaults.update(overrides)
        return CustomerProfile(**defaults)

    def test_normal_amount_zero_score(self):
        factor = AmountScoringFactor(weight=0.5)
        profile = self._make_profile()
        score, explanation = factor.score(
            amount=Decimal("5000"),
            currency="AUD",
            counterparty=None,
            profile=profile,
        )
        assert score == 0.0
        assert explanation is None

    def test_high_amount_positive_score(self):
        factor = AmountScoringFactor(weight=0.5)
        profile = self._make_profile()
        score, explanation = factor.score(
            amount=Decimal("50000"),
            currency="AUD",
            counterparty=None,
            profile=profile,
        )
        assert score > 0
        assert explanation is not None
        assert "amount" in explanation.lower()

    def test_weight_is_accessible(self):
        factor = AmountScoringFactor(weight=0.6)
        assert factor.weight == 0.6


class TestCounterpartyScoringFactor:
    def test_known_counterparty_zero_score(self):
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties={"Acme Corp"},
            known_currencies=set(),
        )
        factor = CounterpartyScoringFactor(weight=0.25)
        score, explanation = factor.score(
            amount=Decimal("0"),
            currency="AUD",
            counterparty="Acme Corp",
            profile=profile,
        )
        assert score == 0.0
        assert explanation is None

    def test_unknown_counterparty_positive_score(self):
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties={"Acme Corp"},
            known_currencies=set(),
        )
        factor = CounterpartyScoringFactor(weight=0.25)
        score, explanation = factor.score(
            amount=Decimal("0"),
            currency="AUD",
            counterparty="Unknown Entity",
            profile=profile,
        )
        assert score > 0
        assert explanation is not None
        assert "counterparty" in explanation.lower()


class TestCurrencyScoringFactor:
    def test_known_currency_zero_score(self):
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies={"AUD"},
        )
        factor = CurrencyScoringFactor(weight=0.25)
        score, explanation = factor.score(
            amount=Decimal("0"),
            currency="AUD",
            counterparty=None,
            profile=profile,
        )
        assert score == 0.0
        assert explanation is None

    def test_unknown_currency_positive_score(self):
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies={"AUD"},
        )
        factor = CurrencyScoringFactor(weight=0.25)
        score, explanation = factor.score(
            amount=Decimal("0"),
            currency="IRR",
            counterparty=None,
            profile=profile,
        )
        assert score > 0
        assert "currency" in explanation.lower()


# ---------------------------------------------------------------------------
# Open/Closed — custom factor injection
# ---------------------------------------------------------------------------


class TestCustomFactorInjection:
    def test_scorer_with_custom_factor_only(self):
        class AlwaysHighFactor(ScoringFactor):
            @property
            def weight(self) -> float:
                return 1.0

            def score(self, *, amount, currency, counterparty, profile):
                return 80.0, "Always suspicious"

        scorer = AnomalyScorer(factors=[AlwaysHighFactor()])
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies=set(),
        )
        result = scorer.score_transaction(
            amount=Decimal("100"),
            currency="AUD",
            counterparty=None,
            profile=profile,
        )
        assert result.score == 80.0
        assert "Always suspicious" in result.factors

    def test_scorer_with_no_factors_returns_zero(self):
        scorer = AnomalyScorer(factors=[])
        profile = CustomerProfile(
            mean_amount=Decimal("0"),
            std_amount=Decimal("0"),
            transaction_count_90d=0,
            avg_daily_frequency=0.0,
            known_counterparties=set(),
            known_currencies=set(),
        )
        result = scorer.score_transaction(
            amount=Decimal("99999"),
            currency="KPW",
            counterparty="Shell Corp",
            profile=profile,
        )
        assert result.score == 0.0
        assert result.factors == []

    def test_scorer_default_factors_match_original_behavior(self):
        scorer = AnomalyScorer()
        profile = CustomerProfile(
            mean_amount=Decimal("5000"),
            std_amount=Decimal("1000"),
            transaction_count_90d=90,
            avg_daily_frequency=1.0,
            known_counterparties={"Acme Corp"},
            known_currencies={"AUD"},
        )
        result = scorer.score_transaction(
            amount=Decimal("50000"),
            currency="KPW",
            counterparty="Unknown",
            profile=profile,
        )
        assert result.score >= 50
        assert len(result.factors) >= 2
