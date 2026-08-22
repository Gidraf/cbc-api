# 03 Admin Control Plane Module

Purpose:
- Define admin workflows for datasets, prompt management, generation triggers, and approvals.

Owns:
- Admin tabs and operational controls
- One-time setup and periodic revision flows

Inputs:
- Admin actions from UI or CLI

Outputs:
- Triggered jobs, context updates, prompt updates, and approval actions

Interacts With:
- ../../services/api-gateway/agents.md
- ../../services/context-layer-langfuse/agents.md
- ../../services/prompt-registry/agents.md
- ../../services/generation-pipeline/agents.md
- ../../services/review-approver-module/agents.md
- ../../services/human-review-publishing/agents.md

Tabs:
- Datasets
- Context Builder
- Prompt Builder
- Generation (notes-first)
- Review and Approval
- Production Readiness
