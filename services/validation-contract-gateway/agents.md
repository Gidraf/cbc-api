# Validation Contract Gateway Module

Purpose:
- Define contract and schema validation boundaries before and after generation.

Owns:
- Request envelope validation
- Response envelope validation
- Question answer completeness validation
- KICD evidence field validation

Inputs:
- Inbound requests from API gateway
- Outbound generated artifacts from pipeline modules

Outputs:
- Validation pass or structured validation errors

Interacts With:
- ../api-gateway/agents.md
- ../generation-pipeline/agents.md
- ../question-module/agents.md
- ../../global/shared-contracts/agents.md
- ../../global/observability-security/agents.md

Checks:
- Reject payloads missing required fields.
- Reject question batches missing required written-response ratio.
- Reject questions without answers and KICD guideline evidence.
