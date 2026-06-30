import uuid
import xml.etree.ElementTree as ET

from aml.services.reporting.submission.protocol import (
    RegulatorySubmissionAdapter,
    SubmissionResult,
    SubmissionStatus,
)


class NZFIUAdapter(RegulatorySubmissionAdapter):
    def __init__(self, *, mock_mode: bool = True) -> None:
        self._mock_mode = mock_mode

    async def format_payload(self, report_type: str, narrative: dict[str, str]) -> bytes:  # noqa: ARG002
        root = ET.Element("goAML_SAR")

        for section_name, content in narrative.items():
            el = ET.SubElement(root, section_name.lower().replace(" ", "_"))
            el.text = content

        return ET.tostring(root, encoding="unicode").encode("utf-8")

    async def submit(self, payload: bytes) -> SubmissionResult:
        if self._mock_mode:
            ref = f"NZFIU-MOCK-{uuid.uuid4().hex[:8].upper()}"
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
