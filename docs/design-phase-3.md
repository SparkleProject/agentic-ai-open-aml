# Phase 3: Regulatory Reporting & ANZ Compliance

## 1. Objectives
Automate the most labor-intensive portion of AML compliance: regulatory reporting. Focus specifically on the AUSTRAC (Australia) and NZ FIU requirements to align with the impending Tranche 2 rollout.

## 2. Core Components

### 2.1 SAR/SMR Narrative Agent (BE-301)
- **Role**: A highly specialized agent trained specifically on AUSTRAC/NZ FIU report formatting.
- **Workflow**:
  - Takes the structured findings from the Agent Orchestrator.
  - Drafts a natural language narrative detailing the "who, what, where, when, and why" of the suspicious activity.
  - Implements a "Chain of Verification" where it self-checks the generated narrative against the original evidence to prevent hallucinations in regulatory submissions.

### 2.2 KYC/CDD Automation Pipeline (BE-302)
- **Role**: Continuous monitoring and initial onboarding for Tranche 2 entities.
- **Integration**: Plugs into local ANZ identity verification APIs (e.g., GreenID, FrankieOne).
- **Execution**: Automatically calculates a dynamic risk score based on PEP status, adverse media, and demographic risk factors.

### 2.3 Entity Unwrapping & Corporate Structure Analysis (BE-304)
- **Role**: Tranche 2 entities (like real estate and accounting) often deal with complex corporate trusts.
- **Workflow**:
  - Connects to ASIC (AU) and NZBN (NZ) registries.
  - Recursively fetches ownership layers until the Ultimate Beneficial Owner (UBO) is reached.
  - Builds a graph structure capable of identifying hidden relationships.

### 2.4 Regulatory Report Submission API (BE-303)
- **Role**: Programmatic B2B submission of approved reports directly to the regulator.
- **Workflow**:
  - Exposes an interface for final submission via AUSTRAC Online/NZ FIU XML gateways.
  - Implements secure queueing, receipt generation, and retry logic in case of regulator downtime.
