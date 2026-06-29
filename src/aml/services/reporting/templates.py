from typing import ClassVar

from pydantic import BaseModel


class TemplateSection(BaseModel):
    name: str
    description: str
    max_words: int
    required: bool
    guidance: str


class FieldConstraint(BaseModel):
    field_name: str
    max_length: int
    required: bool = True
    format_hint: str | None = None


class ReportTemplate(BaseModel):
    report_type: str
    sections: list[TemplateSection]
    field_constraints: dict[str, FieldConstraint]
    system_prompt_addendum: str

    @property
    def required_section_names(self) -> list[str]:
        return [s.name for s in self.sections if s.required]


class TemplateRegistry:
    _built_in: ClassVar[dict[str, ReportTemplate]] = {}

    def __init__(self) -> None:
        self._templates: dict[str, ReportTemplate] = {}
        if not TemplateRegistry._built_in:
            TemplateRegistry._built_in = _build_defaults()
        self._templates.update(TemplateRegistry._built_in)

    def get_template(self, report_type: str) -> ReportTemplate:
        if report_type not in self._templates:
            raise KeyError(f"Unknown report type: {report_type}")
        return self._templates[report_type]

    def list_templates(self) -> list[str]:
        return list(self._templates.keys())

    def register(self, template: ReportTemplate) -> None:
        self._templates[template.report_type] = template


def _build_defaults() -> dict[str, ReportTemplate]:
    return {
        "AUSTRAC_SMR": _austrac_smr(),
        "AUSTRAC_TTR": _austrac_ttr(),
        "AUSTRAC_IFTI": _austrac_ifti(),
        "NZ_SAR": _nz_sar(),
    }


def _austrac_smr() -> ReportTemplate:
    return ReportTemplate(
        report_type="AUSTRAC_SMR",
        sections=[
            TemplateSection(
                name="Subject Details",
                description="Full identification details of the person or entity subject to the report",
                max_words=500,
                required=True,
                guidance="Include full legal name, date of birth, address, nationality, and all account numbers.",
            ),
            TemplateSection(
                name="Suspicious Activity Description",
                description="Detailed description of the suspicious conduct or transactions",
                max_words=1500,
                required=True,
                guidance=(
                    "Describe what activity is suspicious and why. "
                    "Reference specific transactions by ID. Cite evidence sources using [SOURCE-N] tags."
                ),
            ),
            TemplateSection(
                name="Transaction Details",
                description="Itemised list of relevant transactions with dates, amounts, and counterparties",
                max_words=1000,
                required=True,
                guidance="List each transaction: date, amount, currency, direction, counterparty. Include totals.",
            ),
            TemplateSection(
                name="Reporting Entity Information",
                description="Details of the reporting entity submitting the SMR",
                max_words=300,
                required=True,
                guidance="Entity name, ABN/ACN, contact officer name and role.",
            ),
            TemplateSection(
                name="Reason for Suspicion",
                description="Why the reporting entity formed the suspicion",
                max_words=800,
                required=True,
                guidance=(
                    "Explain the basis for suspicion under AML/CTF Act s.41. "
                    "Reference applicable AUSTRAC typologies. Cite all evidence sources."
                ),
            ),
        ],
        field_constraints={
            "subject_name": FieldConstraint(field_name="subject_name", max_length=256, required=True),
            "subject_dob": FieldConstraint(
                field_name="subject_dob",
                max_length=10,
                required=False,
                format_hint="YYYY-MM-DD",
            ),
            "abn": FieldConstraint(
                field_name="abn",
                max_length=11,
                required=False,
                format_hint="11-digit ABN",
            ),
        },
        system_prompt_addendum=(
            "You are drafting an AUSTRAC Suspicious Matter Report (SMR) under the AML/CTF Act 2006. "
            "Use formal regulatory language. Every factual claim must cite a [SOURCE-N] reference. "
            "Do not speculate or include information not present in the provided evidence."
        ),
    )


def _austrac_ttr() -> ReportTemplate:
    return ReportTemplate(
        report_type="AUSTRAC_TTR",
        sections=[
            TemplateSection(
                name="Transaction Details",
                description="Details of the threshold transaction",
                max_words=500,
                required=True,
                guidance="Amount, currency, date, direction, method (cash/EFT).",
            ),
            TemplateSection(
                name="Payer Information",
                description="Details of the person making the transaction",
                max_words=400,
                required=True,
                guidance="Full name, DOB, address, identification document details.",
            ),
            TemplateSection(
                name="Payee Information",
                description="Details of the recipient",
                max_words=400,
                required=True,
                guidance="Full name or entity name, account details.",
            ),
            TemplateSection(
                name="Reporting Entity",
                description="Details of the reporting entity",
                max_words=300,
                required=True,
                guidance="Entity name, ABN, contact officer.",
            ),
        ],
        field_constraints={
            "amount": FieldConstraint(field_name="amount", max_length=20, required=True),
        },
        system_prompt_addendum=(
            "You are drafting an AUSTRAC Threshold Transaction Report (TTR). "
            "This is a factual report of a cash transaction at or above AUD $10,000. "
            "Do not include suspicion language — TTRs are factual, not investigative."
        ),
    )


def _austrac_ifti() -> ReportTemplate:
    return ReportTemplate(
        report_type="AUSTRAC_IFTI",
        sections=[
            TemplateSection(
                name="Transfer Details",
                description="Details of the international funds transfer",
                max_words=500,
                required=True,
                guidance="Amount, currency, date, sending/receiving institutions, SWIFT codes.",
            ),
            TemplateSection(
                name="Ordering Customer",
                description="Details of the person ordering the transfer",
                max_words=400,
                required=True,
                guidance="Full name, address, account number.",
            ),
            TemplateSection(
                name="Beneficiary",
                description="Details of the beneficiary",
                max_words=400,
                required=True,
                guidance="Full name, address, account number, country.",
            ),
            TemplateSection(
                name="Correspondent Banks",
                description="Intermediary institutions involved in the transfer chain",
                max_words=300,
                required=False,
                guidance="Names and SWIFT codes of any intermediary banks.",
            ),
        ],
        field_constraints={
            "swift_code": FieldConstraint(
                field_name="swift_code",
                max_length=11,
                required=True,
                format_hint="8 or 11 char SWIFT/BIC",
            ),
        },
        system_prompt_addendum=(
            "You are drafting an AUSTRAC International Funds Transfer Instruction (IFTI) report. "
            "Include all correspondent banking details. Use ISO country codes."
        ),
    )


def _nz_sar() -> ReportTemplate:
    return ReportTemplate(
        report_type="NZ_SAR",
        sections=[
            TemplateSection(
                name="Reporting Entity Details",
                description="Details of the entity filing the SAR",
                max_words=300,
                required=True,
                guidance="Entity name, NZBN, contact person, role.",
            ),
            TemplateSection(
                name="Subject Details",
                description="Details of the person or entity that is the subject of the SAR",
                max_words=500,
                required=True,
                guidance="Full name, date of birth, address, identification details, relationship to reporting entity.",
            ),
            TemplateSection(
                name="Suspicious Activity Description",
                description="Description of the activity giving rise to the suspicion",
                max_words=1500,
                required=True,
                guidance=(
                    "Describe the suspicious activity in detail. Reference transactions, dates, and amounts. "
                    "Cite evidence using [SOURCE-N] tags. Explain why the activity is unusual."
                ),
            ),
            TemplateSection(
                name="Transaction Details",
                description="Relevant transactions associated with the suspicious activity",
                max_words=1000,
                required=True,
                guidance="Itemise each transaction: date, amount, currency, counterparty, direction.",
            ),
            TemplateSection(
                name="Reason for Suspicion",
                description="Basis for forming the suspicion",
                max_words=800,
                required=True,
                guidance=(
                    "Explain under the AML/CFT Act 2009 why suspicion was formed. "
                    "Reference applicable NZ FIU guidelines and typologies."
                ),
            ),
        ],
        field_constraints={
            "subject_name": FieldConstraint(field_name="subject_name", max_length=256, required=True),
            "nzbn": FieldConstraint(
                field_name="nzbn",
                max_length=13,
                required=False,
                format_hint="13-digit NZBN",
            ),
        },
        system_prompt_addendum=(
            "You are drafting a New Zealand Suspicious Activity Report (SAR) for the NZ FIU "
            "under the Anti-Money Laundering and Countering Financing of Terrorism Act 2009. "
            "Use formal regulatory language. Cite all evidence sources."
        ),
    )
