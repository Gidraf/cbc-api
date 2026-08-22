# 09 Review Approver Module

Purpose:
- Define reviewer panel checks, approver decisioning, verification evidence, and regeneration handoff.

Owns:
- Multi-review scoring contract
- KICD quote verification contract
- Approver decision contract

Inputs:
- Generated artifacts and provenance bundles

Outputs:
- Reviewer outcomes
- Approver outcomes
- Regeneration routing decisions

Interacts With:
- ../generation-pipeline/agents.md
- ../question-module/agents.md
- ../regeneration-module/agents.md
- ../human-review-publishing/agents.md
- ../queue-workflow/agents.md
- ../../global/observability-security/agents.md

Checks:
- Reviewer validates alignment, pedagogy, accuracy, language, and KICD quotes.
- Approver validates reviewer evidence and approves or returns for regeneration.
- Rejected artifacts MUST re-enter the regeneration loop before returning to review.
