# 08 Question Module

Purpose:
- Define mixed assessment generation with both multiple-choice and written-response items.

Owns:
- Question schema, answers schema, KICD quote evidence schema (placeholder)
- Math rendering rules linkage (placeholder)

Inputs:
- Context layers, notes, diagrams, activity context, question prompts

Outputs:
- Question artifacts, explicit answers, marking guides, and question DNA

Interacts With:
- ../generation-pipeline/agents.md
- ../notes-module/agents.md
- ../diagram-module/agents.md
- ../validation-contract-gateway/agents.md
- ../review-approver-module/agents.md
- ../../global/storage-provenance/agents.md
- ../../global/shared-contracts/agents.md

Rules:
- Every batch MUST include both multiple-choice and written-response questions.
- Every question MUST include answers payload and KICD quote evidence.
