# 12 Queue Workflow Module

Purpose:
- Define queue sequencing, retries, regeneration loops, and dead-letter handling.

Owns:
- Queue state transitions
- Retry and failure routing policy

Inputs:
- Jobs from generation, review, and approval modules

Outputs:
- Routed queue events and execution state updates

Interacts With:
- ../platform-orchestration/agents.md
- ../generation-pipeline/agents.md
- ../review-approver-module/agents.md
- ../regeneration-module/agents.md
- ../human-review-publishing/agents.md
- ../../global/observability-security/agents.md

Queue Sequence:
1. generator_queue
2. validation_queue
3. reviewer_queue
4. approver_queue
5. human_review_queue
6. production_ready_queue

Regeneration Loop:
- reviewer or approver rejection -> regeneration_queue -> reviewer_queue -> approver_queue
