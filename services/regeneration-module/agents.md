# Regeneration Module

Purpose:
- Define regeneration handling for rejected artifacts and controlled re-entry into review flow.

Owns:
- Regeneration request contract
- Retry and revision increment logic
- Feedback injection from reviewer and approver

Inputs:
- Rejected artifacts
- Reviewer feedback
- Approver feedback

Outputs:
- Regenerated artifact version
- Routing back to reviewer queue

Interacts With:
- ../review-approver-module/agents.md
- ../queue-workflow/agents.md
- ../generation-pipeline/agents.md
- ../../global/observability-security/agents.md

Rules:
- Regenerated artifacts MUST preserve provenance history.
- Regenerated artifacts MUST return through reviewer and approver stages.
