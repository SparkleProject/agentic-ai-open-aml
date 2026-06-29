# BE-301: SAR/SMR Narrative Agent — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

When an investigation concludes that suspicious activity warrants regulatory reporting, an analyst must draft a Suspicious Activity Report (SAR) for FinCEN-aligned jurisdictions or a Suspicious Matter Report (SMR) for AUSTRAC (Australia). Today, this is a manual process costing 45–90 minutes per report. The existing `SARNarrativeAgent` (BE-204) is a placeholder definition with no tools — it has a system prompt but no report generation logic.

BE-301 builds the **full SAR/SMR Narrative Agent** that:
1. Ingests the structured investigation output from the Agent Orchestrator (BE-202).
2. Drafts a regulator-ready narrative following the exact format required by AUSTRAC SMR, AUSTRAC TTR (Threshold Transaction Report), AUSTRAC IFTI (International Funds Transfer Instruction), and NZ FIU SAR.
3. Implements **Chain of Verification** — the agent self-validates the drafted narrative against the original evidence, flagging any hallucinated facts or unsupported claims.
4. Stores the draft for human review before submission (BE-303).

### Dependencies on Existing Code
- `src/aml/agents/specialized/base.py` — `SARNarrativeAgent` definition (tool_whitelist is currently empty).
- `src/aml/agents/nodes.py` — `reflector_node` currently produces a basic conclusion; this needs to trigger SAR drafting.
- `src/aml/db/models/case.py` — `Case` model with `reasoning` JSONB for the agent XAI trace.
- `src/aml/services/llm/protocol.py` — `LLMProvider.generate_response()`.
- `src/aml/services/rag/service.py` — RAG pipeline for retrieving regulatory formatting guidance.

---

## 2. Architecture Approach: Template-Guided LLM Drafting with Self-Verification

```
  Case + Investigation ──> Template Selector ──> LLM Draft ──> Self-Verification ──> Draft Storage
       Evidence              (by report type)      (structured)    (Chain of Verification)    (DB + API)
```

### 2.1 Report Templates
Each regulatory report type has a structured template defining required sections, field constraints, and formatting rules. Templates are stored as YAML so compliance officers can update them without code changes.

### 2.2 Chain of Verification
After drafting, the agent re-reads the narrative and cross-references every factual claim against the source evidence. Any claim that cannot be traced to a specific transaction, tool result, or KYC record is flagged as `UNVERIFIED`.

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Report Template Models and YAML Templates

**Files:**
- `src/aml/services/reporting/templates.py`
- `data/report_templates/austrac_smr.yaml`
- `data/report_templates/austrac_ttr.yaml`
- `data/report_templates/austrac_ifti.yaml`
- `data/report_templates/nz_sar.yaml`

**Implementation Details:**
- Define `ReportTemplate` Pydantic model:
  - `report_type: str` (e.g., `AUSTRAC_SMR`, `NZ_SAR`)
  - `sections: list[TemplateSection]` — ordered list of required narrative sections.
  - `field_constraints: dict[str, FieldConstraint]` — validation rules (max length, required fields, date formats).
  - `system_prompt_addendum: str` — additional LLM instructions specific to this report format.
- Each `TemplateSection` defines: `name`, `description`, `max_words`, `required: bool`, `guidance: str` (instructions for the LLM).
- Implement `TemplateRegistry` class with `get_template(report_type: str) -> ReportTemplate` and `list_templates() -> list[str]`.
- The AUSTRAC SMR template should include sections: Subject Details, Suspicious Activity Description, Transaction Details, Reporting Entity Information, and Reason for Suspicion.

**Why:** Template-driven generation ensures regulatory format compliance without hardcoding. YAML templates can be updated by compliance teams. The `TemplateRegistry` pattern mirrors the existing `ToolRegistry` and `AgentRegistry` patterns in the codebase.

### Step 2: Build the Narrative Generation Service

**Files:**
- `src/aml/services/reporting/narrative.py`

**Implementation Details:**
- Implement `NarrativeGenerationService`:
  - `async generate_draft(case: Case, report_type: str, tenant_id: str) -> NarrativeDraft`
  - Loads the appropriate `ReportTemplate` from the registry.
  - Collects evidence context:
    - Alert details and triage results from `case.alert`.
    - Agent investigation trace from `case.reasoning`.
    - Customer profile from the linked customer record.
    - Transaction history from the linked transactions.
  - Queries the RAG pipeline for regulatory formatting guidance relevant to the report type.
  - Constructs a structured LLM prompt containing:
    - The template's system_prompt_addendum.
    - All evidence as numbered, labelled source blocks (e.g., `[SOURCE-1: Transaction TXN-9021]`).
    - Instructions to generate each section following the template structure.
    - Instructions to cite sources using `[SOURCE-N]` references.
  - Parses the LLM output into a `NarrativeDraft` model with section-level content.
- `NarrativeDraft` model:
  - `report_type: str`
  - `case_id: UUID`
  - `sections: dict[str, str]` — section name to generated content.
  - `citations: list[Citation]` — source references used.
  - `verification_status: str` — `PENDING`, `VERIFIED`, `HAS_WARNINGS`.
  - `warnings: list[str]` — any unverified claims.

**Why:** Centralising narrative generation in a service (not inside an agent node) allows reuse from both the LangGraph orchestrator and the API layer. Source-citing ensures every claim in the narrative is traceable — critical for regulatory credibility.

### Step 3: Implement Chain of Verification

**Files:**
- `src/aml/services/reporting/verification.py`

**Implementation Details:**
- Implement `NarrativeVerifier`:
  - `async verify(draft: NarrativeDraft, evidence: EvidenceBundle) -> VerificationResult`
  - Sends the draft narrative + the original evidence to the LLM with a verification-specific prompt:
    - "For each factual claim in the narrative, check if it is supported by the provided evidence. Flag any claim that cannot be traced to a specific source."
  - Parses the LLM's response into a list of `VerificationFinding`:
    - `claim: str` — the specific sentence or fact.
    - `status: str` — `VERIFIED`, `UNVERIFIED`, `PARTIALLY_VERIFIED`.
    - `source_ref: str | None` — the source it maps to (if verified).
    - `suggestion: str | None` — recommended fix for unverified claims.
  - Updates the `NarrativeDraft.verification_status` and `warnings` fields.
- The verification prompt uses a lower temperature (0.1) for deterministic checking.

**Why:** Chain of Verification prevents the most dangerous failure mode in AI-assisted regulatory reporting: hallucinated facts in a legal document. This is the critical safety layer that makes AI-drafted narratives trustworthy. The separate verification pass (rather than asking the same model to "be careful") uses a distinct prompt context, reducing the risk of confirmation bias.

### Step 4: Create Report Data Models and Database Storage

**Files:**
- `src/aml/db/models/report.py`

**Implementation Details:**
- Define `Report` ORM model extending `TenantMixin, Base`:
  - `case_id: UUID` (FK to `cases.id`)
  - `report_type: str` (AUSTRAC_SMR, NZ_SAR, etc.)
  - `status: ReportStatus` (DRAFT, IN_REVIEW, APPROVED, SUBMITTED, REJECTED)
  - `narrative: dict[str, Any]` (JSONB — the sections dict)
  - `evidence_snapshot: dict[str, Any]` (JSONB — frozen evidence at draft time)
  - `verification_result: dict[str, Any]` (JSONB — Chain of Verification output)
  - `submitted_at: datetime | None`
  - `submission_reference: str | None` (receipt from AUSTRAC/NZ FIU)
  - `reviewed_by: str | None` (analyst who approved)
- Add relationship on `Case`: `reports: Mapped[list["Report"]]`.

**Why:** Reports need their own lifecycle distinct from Cases. A Case may generate multiple reports (e.g., an SMR and a TTR). The `evidence_snapshot` freezes evidence at draft time so the report remains internally consistent even if the underlying data changes.

### Step 5: Create Reporting API Router

**Files:**
- `src/aml/api/routers/reports.py`

**Implementation Details:**
- `POST /api/v1/cases/{case_id}/reports/draft` — Triggers narrative generation for a given case and report type.
  - Request body: `{ "report_type": "AUSTRAC_SMR" }`
  - Returns the `NarrativeDraft` with verification status.
- `GET /api/v1/reports/{report_id}` — Retrieves a specific report with its narrative and verification results.
- `PUT /api/v1/reports/{report_id}` — Updates narrative sections (analyst edits before submission).
- `POST /api/v1/reports/{report_id}/verify` — Re-runs Chain of Verification after edits.
- `POST /api/v1/reports/{report_id}/approve` — Marks the report as approved (requires appropriate RBAC role).
- Register router in `app.py` at `prefix="/api/v1"`.

**Why:** The FE SMRWorkspace (`src/pages/SMRWorkspace.tsx`) already expects endpoints for drafting, editing, and submitting reports. Currently it uses `fetchMockSMRDraft()`. This API replaces the mock with real backend calls. The verify/approve endpoints support the human-in-the-loop workflow required by regulators.

### Step 6: Update Agent Orchestrator Integration

**Files:**
- `src/aml/agents/specialized/base.py` (update)
- `src/aml/agents/nodes.py` (update)

**Implementation Details:**
- Update `SARNarrativeAgent` definition to include a new tool: `NarrativeDraftTool` in its whitelist.
- Create `NarrativeDraftTool` in `src/aml/agents/tools/local/reporting.py`:
  - A tool the SARNarrativeAgent can invoke to trigger `NarrativeGenerationService.generate_draft()`.
  - Input schema: `{ "case_id": "...", "report_type": "AUSTRAC_SMR" }`.
  - Returns the generated narrative sections as JSON.
- Update `reflector_node`: when the investigation concludes with a recommendation to file a report, automatically delegate to the `SARNarrativeAgent` to draft it.

**Why:** This integrates the narrative generation into the existing agentic workflow. The `SARNarrativeAgent` was defined in BE-204 specifically for this purpose — now it has an actual tool to call.

### Step 7: Implement Tests

**Files:**
- `tests/test_narrative_generation.py`
- `tests/test_narrative_verification.py`

**Implementation Details:**
- Test template loading and section validation.
- Test narrative generation with mocked LLM responses: verify sections match template structure.
- Test Chain of Verification: provide a narrative with one hallucinated claim, verify the verifier catches it.
- Test the API: draft → edit → verify → approve workflow.
- Test the `NarrativeDraftTool` integration with the agent orchestrator.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Hallucinated facts in regulatory submissions** | Critical (legal liability) | Chain of Verification (Step 3). Human review mandatory before submission. |
| **Template format drift** as regulators update requirements | Medium | YAML-based templates updatable without code changes. Version-controlled templates. |
| **LLM output not parseable** into sections | Medium | Structured prompting with XML-like section markers. Fallback: return raw text with a parsing warning. |
| **Evidence context too large** for context window | Medium | Context compression via RAG extractive summarisation. Prioritise most relevant evidence. |
