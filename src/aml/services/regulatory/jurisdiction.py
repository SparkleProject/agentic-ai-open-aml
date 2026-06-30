from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class JurisdictionConfig:
    code: str
    regulator: str
    report_types: list[str]
    currency: str
    thresholds: dict[str, float] = field(default_factory=dict)


JURISDICTIONS: dict[str, JurisdictionConfig] = {
    "AU": JurisdictionConfig(
        code="AU",
        regulator="AUSTRAC",
        report_types=["AUSTRAC_SMR", "AUSTRAC_TTR", "AUSTRAC_IFTI"],
        currency="AUD",
        thresholds={"reporting_threshold": 10000, "structuring_window_hours": 48},
    ),
    "NZ": JurisdictionConfig(
        code="NZ",
        regulator="NZ_FIU",
        report_types=["NZ_SAR"],
        currency="NZD",
        thresholds={"structuring_window_hours": 48},
    ),
    "US": JurisdictionConfig(
        code="US",
        regulator="FinCEN",
        report_types=["FINCEN_SAR", "FINCEN_CTR"],
        currency="USD",
        thresholds={"reporting_threshold": 10000, "sar_threshold": 5000},
    ),
    "GB": JurisdictionConfig(
        code="GB",
        regulator="FCA",
        report_types=["FCA_SAR"],
        currency="GBP",
        thresholds={},
    ),
}


class JurisdictionRegistry:
    _CONFIGS: ClassVar[dict[str, JurisdictionConfig]] = JURISDICTIONS

    def get_config(self, code: str) -> JurisdictionConfig | None:
        return self._CONFIGS.get(code.upper())

    def list_supported(self) -> list[str]:
        return list(self._CONFIGS.keys())

    def get_report_types(self, code: str) -> list[str]:
        config = self.get_config(code)
        return config.report_types if config else []
