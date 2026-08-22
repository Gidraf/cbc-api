# 15 Shared Contracts Module

Purpose:
- Define shared schemas, enums, IDs, and cross-module validation artifacts.

Owns:
- Common request and response envelope schemas
- Shared error codes and status enums
- Question answer and KICD evidence schema rules

Inputs:
- Contract updates from all modules

Outputs:
- Versioned shared contract package for all services

Interacts With:
- ../../services/validation-contract-gateway/agents.md
- ../../services/generation-pipeline/agents.md
- ../../services/question-module/agents.md
- ../../services/api-gateway/agents.md

Validation Focus:
- Request schema validation
- Response schema validation
- Question answers completeness validation
