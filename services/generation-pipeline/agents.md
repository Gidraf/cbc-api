# 04 Generation Pipeline Module

Purpose:
- Define notes-first generation flow, dependency sequencing, and staged handoffs.

Owns:
- Stage sequencing contract:
	1. notes
	2. diagram discovery from notes
	3. diagrams
	4. activities
	5. mixed questions (MCQ + written response)
- Artifact assembly contract for reviewer queue

Inputs:
- Context bundle (global + grade-subject + strand + sub-strand + artifact prompt)
- Generation trigger and execution policy

Outputs:
- Generated notes, diagrams, activities, and questions queued for validation and review

Interacts With:
- ../notes-module/agents.md
- ../diagram-module/agents.md
- ../activity-module/agents.md
- ../question-module/agents.md
- ../validation-contract-gateway/agents.md
- ../review-approver-module/agents.md
- ../queue-workflow/agents.md
- ../../global/shared-contracts/agents.md

Key Rules:
- Question and note generation are separate services and MUST not be merged.
- Reviewer approval is not final publish state.
- All generated artifacts MUST pass contract validation before entering reviewer queue.
