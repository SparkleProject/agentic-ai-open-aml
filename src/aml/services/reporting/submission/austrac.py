import uuid
import xml.etree.ElementTree as ET

from aml.services.reporting.submission.protocol import (
    RegulatorySubmissionAdapter,
    SubmissionResult,
    SubmissionStatus,
)


class AUSTRACAdapter(RegulatorySubmissionAdapter):
    def __init__(self, *, mock_mode: bool = True) -> None:
        self._mock_mode = mock_mode

    async def format_payload(self, report_type: str, narrative: dict[str, str]) -> bytes:
        root_tag = self._root_tag(report_type)
        root = ET.Element(root_tag)

        for section_name, content in narrative.items():
            el = ET.SubElement(root, self._safe_tag(section_name))
            el.text = content

        return ET.tostring(root, encoding="unicode").encode("utf-8")

    async def submit(self, payload: bytes) -> SubmissionResult:
        if self._mock_mode:
            ref = f"AUSTRAC-MOCK-{uuid.uuid4().hex[:8].upper()}"
            return SubmissionResult(
                success=True,
                reference=ref,
                raw_response={"mock": True, "bytes": len(payload)},
            )
        return SubmissionResult(success=False, error="Live submission not implemented")

    async def check_status(self, reference: str) -> SubmissionStatus:
        if self._mock_mode:
            return SubmissionStatus(status="ACCEPTED", details=f"Mock: {reference} accepted")
        return SubmissionStatus(status="UNKNOWN", details="Live status check not implemented")

    @staticmethod
    def _root_tag(report_type: str) -> str:
        mapping = {
            "AUSTRAC_SMR": "suspicious_matter_report",
            "AUSTRAC_TTR": "threshold_transaction_report",
            "AUSTRAC_IFTI": "international_funds_transfer",
        }
        return mapping.get(report_type, "report")

    @staticmethod
    def _safe_tag(name: str) -> str:
        return name.lower().replace(" ", "_").replace("/", "_")
