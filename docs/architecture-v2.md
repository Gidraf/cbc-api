# CBC Architecture V2

This diagram reflects the implementation-ready architecture with explicit validation boundaries, reviewer and approver stages, regeneration loop, and publish transitions.

```mermaid
flowchart TD
  UI[Next.js Admin UI] --> GW[FastAPI Gateway]
  CLI[CBC Admin CLI] --> GW

  GW --> AUTH[JWT and API Key Auth]
  AUTH --> VCG[Validation Contract Gateway]

  VCG --> ORCH[Platform Orchestration]
  ORCH --> CTX[Langfuse Context Layer]
  ORCH --> PIPE[Generation Pipeline]

  subgraph ContextHierarchy[Context Hierarchy]
    C1[Global BECF Context]
    C2[Grade-Subject Context]
    C3[Strand Context]
    C4[Sub-strand Context]
    C5[Artifact Prompt Context]
  end

  CTX --> C1
  CTX --> C2
  CTX --> C3
  CTX --> C4
  CTX --> C5

  PIPE --> NOTES[Notes Service]
  NOTES --> DDISC[Diagram Discovery]
  DDISC --> DIAG[Diagram Service]
  NOTES --> ACT[Activity Service]
  NOTES --> QGEN[Question Service]
  DIAG --> QGEN
  ACT --> QGEN

  QGEN --> VCG
  VCG --> RQ[Reviewer Queue]

  RQ --> REV[Reviewer Panel]
  REV --> KICD[KICD Quote Verification]
  KICD --> AQ[Approver Queue]

  AQ --> APR[Approver Stage]
  APR -->|return_for_regeneration| REGQ[Regeneration Queue]
  REGQ --> REG[Regeneration Service]
  REG --> RQ

  APR -->|approve_to_human_review| HQ[Human Review Queue]
  HQ --> HR[Human Review Stage]
  HR --> PRQ[Production Ready Queue]
  PRQ --> PUB[Published]

  ORCH --> QW[Queue Workflow]
  QW --> RQ
  QW --> AQ
  QW --> HQ
  QW --> PRQ

  subgraph Storage[Data and Storage]
    PG[(PostgreSQL)]
    S3[(MinIO S3)]
  end

  NOTES --> PG
  DIAG --> S3
  QGEN --> PG
  HR --> PG

  subgraph Governance[Observability and Governance]
    MET[Metrics and SLOs]
    AUD[Audit Logs]
    RBAC[RBAC]
    ERR[Error Taxonomy]
  end

  GW --> MET
  VCG --> AUD
  APR --> AUD
  QW --> MET
  AUTH --> RBAC
  VCG --> ERR
```

## Notes

- Approved is not final publish state.
- Publish requires human review transition to production-ready.
- Validation occurs both at API ingress and artifact egress.
- Question service is separate from note service and enforces mixed assessment output.
