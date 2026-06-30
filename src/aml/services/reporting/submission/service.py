from datetime import UTC, datetime

import structlog

from aml.db.models.report import Report, ReportStatus
from aml.services.reporting.submission.austrac import AUSTRACAdapter
from aml.services.reporting.submission.nz_fiu import NZFIUAdapter
from aml.services.reporting.submission.protocol import (
    RegulatorySubmissionAdapter,
    SubmissionResult,
    SubmissionStatus,
)

logger = structlog.get_logger()

ADAPTER_MAP: dict[str, type[RegulatorySubmissionAdapter]] = {
    "AUSTRAC_SMR": AUSTRACAdapter,
    "AUSTRAC_TTR": AUSTRACAdapter,
    "AUSTRAC_IFTI": AUSTRACAdapter,
    "NZ_SAR": NZFIUAdapter,
}


class ReportSubmissionService:
    def __init__(
        self,
        *,
        adapter_overrides: dict[str, RegulatorySubmissionAdapter] | None = None,
    ) -> None:
        self._adapter_overrides = adapter_overrides or {}

    async def submit_report(self, report: Report) -> SubmissionResult:
        if report.status != ReportStatus.APPROVED:
            return SubmissionResult(
                success=False,
                error=f"Report must be APPROVED to submit, current status: {report.status.value}",
            )

        adapter = self._get_adapter(report.report_type)
        if not adapter:
            return SubmissionResult(
                success=False,
                error=f"No submission adapter for report type: {report.report_type}",
            )

        narrative = report.narrative or {}
        payload = await adapter.format_payload(report.report_type, narrative)
        result = await adapter.submit(payload)

        if result.success:
            report.status = ReportStatus.SUBMITTED
            report.submission_reference = result.reference
            report.submitted_at = datetime.now(tz=UTC)

        return result

    async def check_status(self, report: Report) -> SubmissionStatus:
        if not report.submission_reference:
            return SubmissionStatus(status="UNKNOWN", details="No submission reference")

        adapter = self._get_adapter(report.report_type)
        if not adapter:
            return SubmissionStatus(status="UNKNOWN", details="No adapter")

        return await adapter.check_status(report.submission_reference)

    def _get_adapter(self, report_type: str) -> RegulatorySubmissionAdapter | None:
        if report_type in self._adapter_overrides:
            return self._adapter_overrides[report_type]

        adapter_cls = ADAPTER_MAP.get(report_type)
        if adapter_cls:
            return adapter_cls(mock_mode=True)
        return None
