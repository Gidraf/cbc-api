# CBC AI Educational Content Production System - Agent Runtime Specification

Version: 2.1 (Production Contract-First)
Status: Approved for Implementation
Last Updated: 2026-08-22

---

## 0. Functional Context File Layout for Model Routing

To support granular model context loading (for example with qwen:8b), module context files are organized by functional roots and not under a single solution folder.

Primary entrypoints:
- `app/agents.md`
- `services/agents.md`
- `global/agents.md`
- `docs/architecture-v2.md` (implementation diagram)

Routing guidance:
- Use `app/agents.md` for admin UI and interaction workflows.
- Use `services/agents.md` for orchestration, generation pipeline, agents, queues, and API behavior.
- Use `global/agents.md` for shared contracts, persistence, observability, and security.

Each functional root links to module-level `agents.md` files to keep context slices small and task-specific.

---

## 1. Purpose & Vision

This document defines the normative production runtime contract for the CBC multi-agent educational content generation platform.

### Core Objectives:
- Convert KICD CBC curriculum frameworks and design contexts into verifiable revision notes, practical learning activities, SVG/JSON vector diagrams, assessment questions, and Question DNA metadata.
- Ensure **100% curriculum traceability** to Level, Grade, Learning Area/Subject, Pathway, Track, Strand, Sub-strand, and Specific Learning Outcome (SLO).
- Strictly enforce **Criterion-Referenced Assessment** (evaluating against competency rubrics: *Exceeding*, *Meeting*, *Approaching*, *Below Expectations*; **never** norm-referenced learner ranking).
- Maintain dynamic, decoupled prompt and curriculum context management via **Langfuse**.
- Guarantee reproducible generation with complete cryptographic provenance and vector diagram deduplication.

### Conformance Notation:
- **MUST / SHALL**: Absolute technical requirement.
- **SHOULD**: Strongly recommended unless an architectural exception is approved.
- **MAY**: Optional feature.

---

## 2. Scope and Boundaries

### In Scope:
- Multi-agent execution contracts (input, output, failure modes).
- Dynamic 3-tier context assembly from Langfuse (Global Master, Grade, Subject).
- Senior School Pathway (3) & Track (10) curriculum hierarchy routing.
- Vector diagram SHA-256 deduplication and MinIO S3 storage integration.
- Sub-strand Resource Bundle aggregation (Notes + Activities + Diagrams + Questions).
- Question DNA lineage tracking and lifecycle actions (`re-create`, `regenerate`, `re-review`).
- Multi-aspect Reviewer panel with automated quality gates and release policies.
- Daily generation target engine with milestone event hooks (25%, 50%, 75%, 100%).
- Admin CLI tool (`cbc-cli`) and Admin Dataset Pipeline.
- Security, governance, RBAC, and observability SLOs.

### Non-Goals (Out of Scope for Initial Scope):
- Exam Builder / Paper Assembler UI & PDF Export (deferred per user directive).
- School-level timetable management and pupil billing workflows.

---

## 3. Dynamic Context Layer (Langfuse Architecture)

No curriculum prompt text, essence statements, or specific learning outcomes are hardcoded in the agent source code. All context is fetched and compiled dynamically at runtime.

### 3.1 Three-Tier Context Hierarchy

```
┌────────────────────────────────────────────────────────────────────────┐
│                          LANGFUSE SYSTEM                               │
│                                                                        │
│  [Tier 1: Global Master Context]                                       │
│  Prompt: "cbc-master-context" (label: prod)                            │
│  → BECF Vision, 8 Goals, 7 Competencies, 8 Values, Criterion Rubric    │
│                                                                        │
│  [Tier 2: Grade Datasets]                                              │
│  Datasets: "grade-pp1", "grade-pp2", "grade-1" ... "grade-12"          │
│                                                                        │
│  [Tier 3: Subject Context Items]                                       │
│  Dataset Items within Grade Datasets:                                  │
│  → Metadata: Essence statements, Strands, Sub-strands, SLOs, PCIs      │
│                                                                        │
│  [Agent Prompt Templates]                                              │
│  Prompts: "note-generator", "activity-generator",                      │
│           "diagram-generator", "question-generator", "reviewer-panel"   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Runtime Fetch & Cache
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        LangfuseContextService                          │
│                                                                        │
│  Assembles Execution Context Stack:                                    │
│  1. System Message A: Master BECF Context (Prompt)                     │
│  2. System Message B: Grade & Subject Context (Dataset Item Metadata)  │
│  3. User Message: Compiled Agent Prompt Template with Request Variables│
└────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Canonical Dataset & Item Naming Rules

Grade datasets MUST follow the exact slug format:
- Early Years: `grade-pp1`, `grade-pp2`, `grade-1`, `grade-2`, `grade-3`
- Middle School: `grade-4`, `grade-5`, `grade-6`, `grade-7`, `grade-8`, `grade-9`
- Senior School: `grade-10`, `grade-11`, `grade-12`

Requests referencing invalid grade slugs MUST fail immediately with `INVALID_GRADE_DATASET`.

### 3.3 Provenance & Version Pinning

Every generation transaction MUST record immutable provenance in the database:
- `langfuse_prompt_name`: Name of prompt template.
- `langfuse_prompt_version`: Version integer from Langfuse.
- `langfuse_prompt_label`: Pinned deployment label (`prod`, `staging`, `dev`).
- `dataset_name`: Name of grade dataset.
- `dataset_item_id`: Unique identifier of subject item in Langfuse dataset.
- `dataset_item_version`: Timestamp or version checksum of the dataset item.
- `prompt_hash_sha256`: SHA-256 hash of the fully compiled prompt (after variable injection).
- `model_provider`, `model_name`, `model_revision`, `temperature`, `top_p`.

---

## 4. Global Data Contracts & Identity

### 4.1 Canonical ID Syntax

- **Curriculum Node ID**:
  `[LEVEL]-[GRADE]-[LEARNING_AREA]-[STRAND]-[SUBSTRAND]-[SLO_ID]`
  *Example*: `MS-G7-ISCI-MAT-CLM-01`
- **Question Universal ID**:
  `Q-[GRADE]-[SUBJECT_CODE]-[SLO_ID]-[SEQ_NUM]`
  *Example*: `Q-7-ISCI-MS-G7-ISCI-MAT-CLM-01-01`
- **Diagram ID**:
  `diag_[12-char-lower-hex]`
  *Example*: `diag_a4b9c1d2e3f4`
- **Resource Bundle ID**:
  `res_[12-char-lower-hex]`
  *Example*: `res_7f8a9b0c1d2e`

### 4.2 Standard Request Envelope

All agent invocations MUST adhere to the following payload schema:

```json
{
  "request_id": "req_01J8F0A2B4C6D8E0F2G4H6J8K0",
  "trace_id": "trc_01J8F0A2B4C6D8E0F2G4H6J8K0",
  "tenant_id": "cbc_default",
  "actor": {
    "type": "system|admin|api",
    "id": "usr_admin_01"
  },
  "curriculum": {
    "level": "Middle School",
    "grade": "7",
    "subject": "Integrated Science",
    "subject_code": "ISCI",
    "pathway": null,
    "track": null,
    "strand": "Matter",
    "sub_strand": "Classification of Matter",
    "slo_id": "MS-G7-ISCI-MAT-CLM-01"
  },
  "controls": {
    "idempotency_key": "idem_matter_g7_clm_01_v1",
    "deadline_ms": 120000,
    "max_regen_attempts": 2,
    "environment": "prod"
  }
}
```

### 4.3 Standard Response Envelope

```json
{
  "request_id": "req_01J8F0A2B4C6D8E0F2G4H6J8K0",
  "trace_id": "trc_01J8F0A2B4C6D8E0F2G4H6J8K0",
  "status": "success|failed|partial",
  "agent": "NoteGeneratorAgent",
  "latency_ms": 1840,
  "result": {},
  "errors": [],
  "provenance": {
    "langfuse_prompt_name": "note-generator",
    "langfuse_prompt_version": "v2.1",
    "prompt_hash_sha256": "4a7d...3e1f",
    "model_name": "gemini-3.7-flash",
    "created_at": "2026-08-22T13:45:00Z"
  }
}
```

---

## 5. Agent Roster & Execution Contracts

```
                                  [Admin / API Trigger]
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │  LangfuseContextService   │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │ TopicContextBuilderAgent  │
                              └─────────────┬─────────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    ▼                       ▼                       ▼
          ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
          │ NoteGeneratorAgent│   │ActivityGenerator  │   │   DiagramAgent    │
          │                   │   │Agent              │   │(Vector Dedup/S3)  │
          └─────────┬─────────┘   └─────────┬─────────┘   └─────────┬─────────┘
                    │                       │                       │
                    └───────────────────────┼───────────────────────┘
                                            │ (Linked Diagram ID & S3 URL)
                                            ▼
                              ┌───────────────────────────┐
                              │  QuestionGeneratorAgent   │
                              └─────────────┬─────────────┘
                                            │
                                            ▼
                              ┌───────────────────────────┐
                              │   ReviewerAgents Panel    │
                              │ (Alignment, Pedagogy, QA) │
                              └─────────────┬─────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
                 [Release Approved]                  [Needs Revision]
                          │                                   │
                          ▼                                   ▼
              PostgreSQL & Target Hook               Auto-Regenerate (≤2)
```

---

### 5.1 `LangfuseContextService`
- **Function**: Runtime orchestrator for prompt template retrieval, dataset item fetching, and variable interpolation.
- **Inputs**: Curriculum target identifiers, environment label, requested agent prompt names.
- **Outputs**:
  - `master_context`: Compiled global BECF markdown string.
  - `subject_context`: Parsed JSON metadata for the targeted subject.
  - `agent_messages`: Array of structured message dicts (`[{"role": "system", ...}, {"role": "user", ...}]`).
  - `provenance`: Detailed version and SHA-256 hashes.
- **Error Codes**:
  - `LANGFUSE_UNAVAILABLE`: Network/API timeout communicating with Langfuse (Retryable).
  - `PROMPT_NOT_FOUND`: Target prompt template missing in Langfuse (Fatal).
  - `DATASET_ITEM_NOT_FOUND`: Subject context item missing in grade dataset (Fatal).
  - `PROMPT_COMPILE_ERROR`: Jinja/Variable substitution syntax error (Fatal).

---

### 5.2 `TopicContextBuilderAgent`
- **Function**: Synthesizes the exact sub-strand context packet required by generation agents.
- **Inputs**: Raw Langfuse subject dataset item metadata.
- **Outputs**:
  ```json
  {
    "topic_context": {
      "slo_ids": ["MS-G7-ISCI-MAT-CLM-01"],
      "learning_outcomes": [
        "Classify materials in the immediate environment based on physical properties"
      ],
      "essence_statement": "Integrated Science develops scientific literacy and inquiry skills...",
      "pcis": ["Environmental Education", "Safety and Health"],
      "core_competencies": ["Critical Thinking and Problem Solving", "Communication and Collaboration"],
      "constitutional_values": ["Responsibility", "Respect"],
      "common_misconceptions": [
        "Confusing state of matter (solid/liquid/gas) with weight or mass"
      ],
      "key_vocabulary": ["matter", "physical properties", "density", "solubility", "texture"]
    }
  }
  ```

---

### 5.3 `NoteGeneratorAgent`
- **Function**: Produces comprehensive, pedagogical revision notes tailored to the cognitive level of the target grade.
- **Outputs**:
  ```json
  {
    "title": "Classification of Matter Based on Physical Properties",
    "intro": "In our daily environment, we interact with various materials...",
    "key_concepts": [
      {
        "heading": "What is Matter?",
        "content": "Matter is anything that has mass and occupies space...",
        "pedagogical_notes": "Connect to everyday classroom objects (rulers, water bottles, air in balloons)."
      },
      {
        "heading": "Physical Properties of Materials",
        "content": "Materials can be grouped by texture, hardness, solubility, and state..."
      }
    ],
    "worked_examples": [
      {
        "scenario": "Grouping kitchen items into solids, liquids, and gases",
        "solution_steps": ["Step 1: Identify state of sugar (solid)...", "Step 2: Identify state of cooking oil (liquid)..."],
        "explanation": "Solids maintain definite shape while liquids take the shape of their container."
      }
    ],
    "key_inquiry_questions": [
      "How can we sort different materials found in our school compound?"
    ],
    "summary_points": [
      "Matter exists in solid, liquid, and gas states.",
      "Physical properties help us choose the right material for a specific purpose."
    ],
    "accessibility_support": {
      "plain_language_summary": "Everything around us is matter. We sort them by how they look and feel.",
      "audio_description_notes": "Read bullet points with clear pauses between solid, liquid, and gas examples."
    }
  }
  ```

---

### 5.4 `ActivityGeneratorAgent`
- **Function**: Creates hands-on, experiential, and inquiry-based practical learning activities based on Dewey’s constructivism and Vygotsky’s peer scaffolding.
- **Outputs**:
  ```json
  {
    "activity_name": "Sorting Compound Materials by Physical Properties",
    "objective": "Classify 5 common materials into solids and liquids based on shape retention.",
    "materials": [
      "Locally available empty plastic containers",
      "Small stones, sand, clean water, cooking oil, leaves"
    ],
    "procedure_steps": [
      "1. Work in small groups of 3 to 4 learners.",
      "2. Collect sample materials from the designated safe school area.",
      "3. Place each item on the sorting tray and observe its shape.",
      "4. Transfer water and oil into containers of different shapes and note changes.",
      "5. Record observations in the group learner journal."
    ],
    "safety_notes": [
      "Do not taste or smell unknown liquids.",
      "Wash hands thoroughly with clean running water and soap after the activity."
    ],
    "grouping_mode": "Small collaborative groups (heterogeneous)",
    "assessment_observables": [
      "Learner actively engages with group peers.",
      "Learner correctly describes difference between fixed shape and variable shape."
    ],
    "inclusion_adaptations": [
      {
        "target_need": "Visual Impairment",
        "adaptation": "Use tactile samples with distinct textures (rough stones vs smooth plastic vs liquid in sealed bag)."
      }
    ]
  }
  ```

---

### 5.5 `DiagramAgent` (Vector Generator & Deduplication Engine)

- **Function**: Generates responsive SVG vector markup and JSON primitives, applies deterministic normalization, and deduplicates against existing diagrams in MinIO/S3.
- **Accessibility & SNE Requirement**: MUST include `tactile_description` and `alt_text` for every generated visual asset.

#### Canonicalization & SHA-256 Hash Algorithm:
1. Parse SVG XML tree.
2. Sort all XML attributes alphabetically per element (`<circle cx="10" cy="10" r="5"/>`).
3. Normalize all floating point coordinates to exactly 4 decimal places (`round(val, 4)`).
4. Strip all comments and insignificant whitespace.
5. Extract all text and label nodes, convert to lowercase Unicode Normalization Form C (NFC).
6. Exclude dynamic runtime IDs and timestamps.
7. Compute:
   $$\text{diagram\_hash} = \text{SHA-256}(\text{canonical\_svg\_nodes} + \text{canonical\_labels})$$

#### Outputs:
```json
{
  "diagram_id": "diag_a4b9c1d2e3f4",
  "diagram_title": "States of Matter Particle Arrangement",
  "diagram_svg": "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200'>...</svg>",
  "diagram_json": {
    "type": "particle_model",
    "entities": [{"name": "solid", "particles": 16}, {"name": "liquid", "particles": 12}, {"name": "gas", "particles": 6}]
  },
  "diagram_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "storage_url": "http://minio:9000/cbc-assets/diagrams/states_of_matter_particles.svg",
  "dedup_status": "created|reused",
  "accessibility": {
    "alt_text": "Three boxes showing particle arrangements in solids (tightly packed), liquids (loosely packed), and gases (far apart).",
    "tactile_description": "A tactile diagram with three raised textured squares. Square 1 has dense raised dots. Square 2 has spaced dots. Square 3 has three scattered dots."
  }
}
```

---

### 5.6 `QuestionGeneratorAgent` & Question DNA

- **Function**: Generates criterion-referenced questions linked to sub-strand revision notes and vector diagrams.
- **Mandatory Answer Requirement**: Every generated question MUST include an explicit answer payload suitable for learner feedback, marking automation, and human moderation.
- **Mandatory KICD Citation Requirement**: Every generated question MUST include quoted KICD guideline evidence for the exact subject, strand, sub-strand, and SLO so a parent or teacher can verify alignment.
- **Mixed Assessment Requirement**: Each generated question set MUST include both multiple-choice items and written-response items where learners must write answers (not select options).
- **Question Types Supported**:
  - `multiple_choice`
  - `short_answer`
  - `structured_inquiry`
  - `practical_performance_task`
  - `matching`
  - `cloze`

#### Level-Based Question Mix Policy:
- For every sub-strand batch, include at least:
  - `multiple_choice` >= 30% of total items.
  - written-response items (`short_answer`, `structured_inquiry`, `practical_performance_task`) >= 40% of total items.
- For higher cognitive levels (Application, Analysis, Evaluation, Creation), written-response items are mandatory.
- If a batch contains only selectable-answer items, validation MUST fail with `INSUFFICIENT_WRITTEN_RESPONSE_ITEMS`.

#### Required Answer Fields by Question Type:
- All question objects MUST include `answers`.
- For `multiple_choice`: include `answers.correct_option_ids`.
- For `short_answer|structured_inquiry|practical_performance_task|cloze|matching`: include `answers.expected_response` and `answers.scoring_points`.
- `marking_guide` remains mandatory and must align with `answers`.

#### Required KICD Evidence Fields:
- All question objects MUST include `kicd_guideline_evidence[]`.
- Each evidence item MUST include:
  - `subject`
  - `strand`
  - `sub_strand`
  - `slo_id`
  - `guideline_quote` (verbatim quote from stored KICD context)
  - `guideline_reference` (dataset and item pointer)
  - `parent_teacher_explanation` (plain-language explanation of how the question aligns)

#### Question Schema & Question DNA (v2.1):
```json
{
  "question_id": "Q-7-ISCI-MS-G7-ISCI-MAT-CLM-01-01",
  "universal_id": "MS-G7-ISCI-MAT-CLM-01",
  "curriculum_link": {
    "level": "Middle School",
    "grade": "7",
    "subject": "Integrated Science",
    "subject_code": "ISCI",
    "pathway": null,
    "track": null,
    "strand": "Matter",
    "sub_strand": "Classification of Matter",
    "slo_id": "MS-G7-ISCI-MAT-CLM-01"
  },
  "pedagogical_dna": {
    "core_competencies": ["Critical Thinking and Problem Solving"],
    "constitutional_values": ["Responsibility"],
    "pcis": ["Environmental Education"],
    "cognitive_level": "Application",
    "criterion_difficulty": 0.45,
    "marks": 4
  },
  "content": {
    "question_type": "multiple_choice",
    "question_text": "Grade 7 learners placed a small stone, 50ml of cooking oil, and air inside three separate sealed syringes. When they pushed the piston with equal force, only the syringe with air compressed significantly. Which conclusion is correct?",
    "options": [
      {
        "id": "A",
        "text": "Gases have large spaces between particles that allow compression.",
        "is_correct": true,
        "distractor_rationale": "Correct: Gas particles have high intermolecular spacing."
      },
      {
        "id": "B",
        "text": "Liquids have fixed shapes and cannot be poured.",
        "is_correct": false,
        "distractor_rationale": "Incorrect: Liquids flow and take the shape of their container."
      },
      {
        "id": "C",
        "text": "Solids have particles that move freely at high speeds.",
        "is_correct": false,
        "distractor_rationale": "Incorrect: Solid particles only vibrate about fixed positions."
      },
      {
        "id": "D",
        "text": "Liquids compress more easily than gases.",
        "is_correct": false,
        "distractor_rationale": "Incorrect: Liquids are virtually incompressible compared to gases."
      }
    ],
    "answers": {
      "correct_option_ids": ["A"],
      "expected_response": "Gases have large spaces between particles that allow compression.",
      "scoring_points": [
        "Identifies gases as the compressible state.",
        "Explains particle spacing as the scientific reason."
      ]
    },
    "kicd_guideline_evidence": [
      {
        "subject": "Integrated Science",
        "strand": "Matter",
        "sub_strand": "Classification of Matter",
        "slo_id": "MS-G7-ISCI-MAT-CLM-01",
        "guideline_quote": "Learners should classify materials in the immediate environment based on observable physical properties.",
        "guideline_reference": {
          "dataset_name": "grade-7",
          "dataset_item_id": "itm_isci_matter_01",
          "context_key": "learning_outcomes[0]"
        },
        "parent_teacher_explanation": "This question asks learners to reason about gas compressibility from particle spacing, which is a direct application of classifying matter by physical properties."
      }
    ],
    "diagram_id": "diag_a4b9c1d2e3f4",
    "diagram_url": "http://minio:9000/cbc-assets/diagrams/syringe_compression.svg",
    "marking_guide": {
      "exceeding": "Correctly chooses A, explains molecular spacing difference between gases, liquids, and solids with everyday examples.",
      "meeting": "Correctly chooses A with clear identification of gas compressibility.",
      "approaching": "Identifies that gases compress but confuses solid and liquid behavior.",
      "below": "Fails to identify gas compression or selects incorrect option."
    }
  },
  "written_response_example": {
    "question_type": "structured_inquiry",
    "question_text": "Explain why air in a syringe compresses more than water when equal force is applied. Use particle arrangement language.",
    "answers": {
      "expected_response": "Air compresses more because gas particles are far apart with large spaces, while water particles are closer together and resist compression.",
      "scoring_points": [
        "States that gases have larger particle spacing.",
        "Explains that liquids are less compressible because particles are closer.",
        "Uses correct scientific vocabulary such as particles, spacing, and compression."
      ]
    },
    "marking_guide": {
      "exceeding": "Explains compressibility using accurate particle model language and compares gas with liquid clearly.",
      "meeting": "Correctly explains why gases compress more than liquids.",
      "approaching": "Gives partial explanation but misses particle-spacing reasoning.",
      "below": "Provides incorrect or unrelated explanation."
    }
  },
  "provenance": {
    "model_provider": "google",
    "model_name": "gemini-3.7-flash",
    "model_revision": "2026-08",
    "temperature": 0.2,
    "top_p": 0.9,
    "langfuse_prompt_name": "question-generator",
    "langfuse_prompt_version": "v2.1",
    "langfuse_prompt_label": "prod",
    "dataset_name": "grade-7",
    "dataset_item_id": "itm_isci_matter_01",
    "dataset_item_version": "1.0",
    "prompt_hash_sha256": "4a7d...3e1f",
    "diagram_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "created_at": "2026-08-22T13:45:00Z"
  },
  "review_audit": {
    "alignment_score": 0.98,
    "accuracy_score": 1.0,
    "pedagogy_score": 0.96,
    "language_score": 0.95,
    "kicd_citation_score": 1.0,
    "kicd_citation_check": {
      "status": "verified",
      "verified_quotes": 1,
      "notes": "Quoted KICD outcome matches strand, sub-strand, and SLO context."
    },
    "status": "approved"
  }
}
```

---

### 5.7 `ReviewerAgents` Panel

Four specialized reviewer sub-agents audit every generated artifact before acceptance:
1. **Alignment Reviewer**: Verifies 100% curriculum trace to KICD SLO, Strand, and Grade.
2. **Pedagogy & Assessment Reviewer**: Enforces criterion-referenced rubrics, Bloom's cognitive fit, and eliminates norm-referenced / competitive ranking language.
3. **Accuracy & Fact Reviewer**: Verifies scientific, mathematical, spelling, and factual validity.
4. **Language & Accessibility Reviewer**: Checks age-appropriate vocabulary, SNE inclusion, clarity, and grammatical precision.

#### Reviewer Output Contract:
```json
{
  "review_audit": {
    "alignment_score": 0.98,
    "accuracy_score": 1.0,
    "pedagogy_score": 0.96,
    "language_score": 0.95,
    "kicd_citation_score": 1.0,
    "risk_flags": [],
    "status": "approved|needs_revision|rejected",
    "kicd_quote_verification": {
      "status": "verified|failed",
      "missing_or_invalid_quotes": [],
      "validated_references": [
        {
          "dataset_name": "grade-7",
          "dataset_item_id": "itm_isci_matter_01",
          "context_key": "learning_outcomes[0]"
        }
      ]
    },
    "feedback": [
      {
        "reviewer": "PedagogyReviewer",
        "aspect": "rubric_clarity",
        "comment": "Criterion standards for Approaching vs Meeting are clear and distinct."
      }
    ]
  }
}
```

---

### 5.8 Sub-strand Resource Bundle Aggregation

The system aggregates all verified artifacts for a sub-strand into an atomic bundle entity:

```json
{
  "bundle_id": "res_7f8a9b0c1d2e",
  "curriculum": {
    "level": "Middle School",
    "grade": "7",
    "subject": "Integrated Science",
    "strand": "Matter",
    "sub_strand": "Classification of Matter"
  },
  "notes": { "$ref": "note_01J8F..." },
  "activities": [{ "$ref": "act_01J8F..." }],
  "diagrams": [{ "$ref": "diag_a4b9c1d2e3f4" }],
  "questions": [
    { "$ref": "Q-7-ISCI-MS-G7-ISCI-MAT-CLM-01-01" },
    { "$ref": "Q-7-ISCI-MS-G7-ISCI-MAT-CLM-01-02" }
  ],
  "status": "published",
  "updated_at": "2026-08-22T13:45:00Z"
}
```

---

## 6. Question Lifecycle & Actions

| Action | Target Scope | Description | Idempotency / Cache Rule |
|---|---|---|---|
| `re-create` | SLO Level | Discards current item and generates a completely new concept and context for the same SLO. | Generates new `question_id`. |
| `regenerate` | Question Level | Preserves current question core concept, but refines phrasing, diagram, or distractor rationales. | Keeps `question_id`, increments revision count. |
| `re-review` | Audit Level | Re-runs only the `ReviewerAgents` panel against current Langfuse quality criteria without altering question text. | Updates `review_audit` in-place. |

---

## 7. Quality Gates, Auto-Rejection & Release Policy

### 7.1 Threshold Requirements for Approval:
- $\text{alignment\_score} \ge 0.95$
- $\text{accuracy\_score} \ge 0.98$
- $\text{pedagogy\_score} \ge 0.93$
- $\text{language\_score} \ge 0.90$
- **Zero Critical Risk Flags** present.

### 7.2 Critical Risk Flags (Trigger Instant Auto-Reject):
1. `FACTUAL_ERROR_IN_KEY`: Answer key or explanation is mathematically/scientifically incorrect.
2. `NORM_REFERENCED_RANKING`: Item uses ranking, grading curves, or compares learner against peers.
3. `SAFETY_VIOLATION`: Practical activity procedure instructs hazardous or unsupervised chemical/physical handling.
4. `UNTRACEABLE_SLO`: Content cannot be matched to KICD curriculum design outcomes.
5. `COPYRIGHT_INFRINGEMENT`: Content matches verbatim copyrighted textbook passages.

### 7.3 Auto-Regeneration Policy:
- On failure of soft score thresholds (e.g. `language_score = 0.88`), the system auto-regenerates with reviewer feedback injected as corrective guidance up to **2 times**.
- On third consecutive failure, status is set to `needs_human_review` and routed to the human moderation queue.

---

## 8. Daily Generation Targets & Milestone Notification Engine

The system tracks daily generation progress against configurable daily targets and emits milestone event hooks.

### 8.1 Milestone Schedule & Deduplication
- Milestones fire at: **25%**, **50%**, **75%**, and **100%** of daily target.
- **Idempotency Guarantee**: A milestone notification for a given date and tier (`2026-08-22_tier_50`) MUST fire **at most once per calendar day**.

### 8.2 Milestone Event Payload Schema:
```json
{
  "event_id": "evt_milestone_20260822_50",
  "event_type": "generation.milestone_reached",
  "timestamp": "2026-08-22T13:45:00Z",
  "data": {
    "date": "2026-08-22",
    "milestone_tier": "50%",
    "target_count": 1000,
    "completed_count": 512,
    "approved_count": 498,
    "rejected_count": 14,
    "breakdown_by_grade": {
      "grade-7": 320,
      "grade-8": 192
    },
    "recipients": ["admin@cbc-platform.ke", "lead_curriculum@cbc-platform.ke"]
  }
}
```

---

## 9. Failure Handling, Retries & Timeouts

### 9.1 Retry Matrix

| Failure Category | Max Attempts | Backoff Strategy | Policy |
|---|---|---|---|
| Langfuse API Transient | 3 | Exponential ($500\text{ms}, 1500\text{ms}, 3500\text{ms}$) | Retryable |
| LLM Provider Timeout / 429 | 3 | Exponential with jitter ($1\text{s}, 3\text{s}, 7\text{s}$) | Retryable |
| MinIO S3 Upload Error | 3 | Linear ($1000\text{ms}$) | Retryable |
| Schema Validation Error | 0 | None | Non-retryable (Fix prompt/schema) |
| Missing Curriculum Context | 0 | None | Non-retryable (Requires dataset upload) |

### 9.2 Execution Timeouts
- **Context Fetch Timeout**: $8\text{ seconds}$
- **Single Agent Generation Timeout**: $45\text{ seconds}$
- **Reviewer Panel Timeout**: $20\text{ seconds}$
- **Total Pipeline Request Deadline**: $120\text{ seconds}$

---

## 10. Standardized System Error Code Taxonomy

| Error Code | HTTP Status | Retryable | Description |
|---|---|---|---|
| `LANGFUSE_UNAVAILABLE` | 503 | Yes | Unable to connect to Langfuse API. |
| `PROMPT_NOT_FOUND` | 404 | No | Specified prompt template missing in Langfuse. |
| `DATASET_ITEM_NOT_FOUND` | 404 | No | Specified subject context item missing in grade dataset. |
| `INVALID_GRADE_DATASET` | 400 | No | Grade identifier does not conform to `grade-pp1`..`grade-12`. |
| `DIAGRAM_GENERATION_FAILED` | 502 | Yes | SVG parser failed to produce valid XML markup. |
| `STORAGE_UPLOAD_FAILED` | 502 | Yes | MinIO S3 client failed to persist asset. |
| `QUALITY_GATE_REJECTED` | 422 | No | Artifact failed quality thresholds after max retries. |
| `CRITICAL_RISK_FLAG` | 422 | No | Auto-rejected due to critical risk violation. |
| `IDEMPOTENCY_CONFLICT` | 409 | No | Request with same idempotency key is currently executing. |
| `UNAUTHORIZED_ACCESS` | 401 | No | Missing or invalid JWT token / Developer API Key. |

---

## 11. Admin CLI Specification (`cbc-cli`)

The platform includes a command-line tool (`cbc-cli`) executable via terminal for administrative, maintenance, and dataset operations:

```bash
# 1. Credential Management
cbc-cli reset-admin-password --email admin@cbc-platform.ke

# 2. Langfuse Dataset Operations
cbc-cli langfuse list-datasets
cbc-cli langfuse show-grade --grade 7
cbc-cli langfuse show-subject --grade 7 --subject "Integrated Science"
cbc-cli langfuse upload-context --grade 7 --subject "Mathematics" --file ./curriculum/grade7_math.json

# 3. Direct Content Generation Trigger
cbc-cli generate --grade 7 --subject "Integrated Science" --strand "Matter" --substrand "Classification of Matter"

# 4. Target Engine Status
cbc-cli targets status --date today
```

---

## 12. Security, Access Control & Observability

### 12.1 Role-Based Access Control (RBAC)
- **`admin`**: Full dataset upload, Langfuse prompt label reassignment, CLI credential management.
- **`operator`**: Generation job triggers, daily target configuration, batch retry.
- **`reviewer`**: Quality audit review, human-in-the-loop override approval.
- **`developer`**: Read-only access to Question Bank & Question DNA via Developer API Keys (`cbc_live_...`).

### 12.2 Observability & Production SLO Targets
- **Pipeline Availability**: $\ge 99.0\%$ uptime.
- **p95 Total Generation Latency**: $\le 90\text{ seconds}$.
- **Post-Approval Critical Factual Error Rate**: $\le 0.1\%$.
- **Diagram Deduplication Hit Ratio Tracking**: Monitored in Grafana / Langfuse metrics.

---

## 13. Admin Experience and Operational Tabs

The admin interface MUST expose an operations console with distinct tabs to support one-time setup and recurring revision workflows.

### 13.1 Required Admin Tabs
1. **Datasets Tab**
- Browse all Langfuse datasets.
- View dataset items by grade, subject, strand, sub-strand.
- Upload and version global BECF context and grade-subject context.

2. **Context Builder Tab**
- Generate and preview suggested strand and sub-strand context objects from grade-subject datasets.
- Save approved strand and sub-strand context objects back to Langfuse dataset items.

3. **Prompt Builder Tab**
- Create and version prompts for notes, activities, diagrams, questions, reviewers, and regeneration.
- Map each prompt to explicit required context keys.

4. **Generation Tab (Notes First)**
- Trigger generation by grade, subject, strand, sub-strand.
- Stage 1: notes generation.
- Stage 2: diagram discovery from notes and diagram generation.
- Stage 3: activity generation and question generation using notes + diagrams + context.

5. **Review and Approval Tab**
- Reviewer queue and Approver queue.
- Approver MUST be able to run guided web verification for factual checks before final acceptance.
- Decision actions: `approve`, `reject`, `request_regeneration`.

6. **Production Readiness Tab**
- Human review queue for final sign-off.
- Publish approved artifacts to production-ready state.

7. **Model Routing and Keys Tab**
- Admin MUST be able to configure provider credentials for `openai`, `anthropic`, `gemini`, and `ollama`.
- Admin MUST be able to select provider + model per pipeline stage (notes, diagrams, activities, questions, reviewers, regeneration).
- Admin MUST be able to define custom Ollama base URL and available Ollama model name(s).
- For `openai`, `anthropic`, and `gemini`, system base URLs MUST default to official provider endpoints.

### 13.2 Admin Use Pattern
- This console is primarily used during initial curriculum setup and occasionally reused when KICD guidance is revised or content quality audits require refresh.

---

## 14. Two-Step Operating Model

The platform SHALL support two major lifecycle phases.

### 14.1 Step A: Context and Prompt Foundation (Mostly One-Time)
1. Admin manually prepares and uploads:
- Global BECF context.
- Grade-subject guideline text.

2. Agents generate draft context layers:
- Strand context per grade-subject.
- Sub-strand context per strand.

3. Reviewer and Approver evaluate draft context layers.

4. Approved context layers are saved and versioned in Langfuse.

5. Prompt templates are authored and versioned in Langfuse for all generator and reviewer roles.

### 14.2 Step B: Content Production and Periodic Revision
1. Use approved context and prompts to generate notes, diagrams, activities, and questions.
2. Review with multi-agent panel.
3. Approver runs web-backed verification and decides pass or regenerate.
4. On pass, content is saved for human review and then marked production-ready.
5. On fail, content enters regeneration loop and returns to reviewer queue.

---

## 15. Expanded Context Chain and Notes-First Pipeline

### 15.1 Mandatory Context Chain per Generation
Every generation and review operation MUST be grounded on this layered context chain:
1. Global BECF context.
2. Grade-subject context.
3. Strand context.
4. Sub-strand context.
5. Artifact-specific context prompt (`notes-context`, `diagram-context`, `activity-context`, `question-context`, `review-context`).

If any required layer is missing, the request MUST fail with `MISSING_CONTEXT_LAYER`.

### 15.2 Notes-First Orchestration
Production generation MUST run in this dependency order:
1. Generate notes first.
2. Analyze notes to discover required diagrams and visual objects.
3. Generate diagrams and store linked diagram assets.
4. Generate activities using context + notes + diagrams where relevant.
5. Generate questions using context + notes + diagrams + activities.

Question categories MUST support:
- theory questions
- experiment or practical questions
- diagram-linked questions

---

## 16. Dynamic Object Model and Storage Rules

To avoid hardcoded payload assumptions, artifact objects MUST support a dynamic extension model.

### 16.1 Dynamic Schema Pattern
All artifact objects SHALL include:
- `core`: required stable fields for contract compatibility.
- `extensions`: dynamic key-value object for context-specific attributes.
- `object_version`: schema evolution marker.

Example pattern:

```json
{
  "artifact_type": "note",
  "core": {
    "title": "...",
    "summary": "..."
  },
  "extensions": {
    "local_examples": [...],
    "activity_hooks": [...],
    "teacher_tips": [...],
    "rendering": {
      "math_mode": "latex+text"
    }
  },
  "object_version": "1.0"
}
```

### 16.2 Dynamic Key Governance
- Unknown extension keys MAY be saved when they pass safety and schema guards.
- Extension key registry SHOULD be tracked per artifact type to monitor drift.
- Core contract fields MUST remain backward compatible.

---

## 17. Reviewer, Approver, and Regeneration Queues

### 17.1 Queue Sequence
1. `generator_queue`
2. `reviewer_queue`
3. `approver_queue`
4. `human_review_queue`
5. `production_ready`

### 17.2 Approver Agent Requirements
- Approver evaluates reviewer outputs and can perform guided web verification for factual confirmation.
- External verification findings MUST be captured as structured evidence with source links and timestamps.
- Approver decisions:
  - `approve_to_human_review`
  - `return_for_regeneration`
  - `reject`

### 17.3 Regeneration Agent Contract
- Input: failed artifact, reviewer feedback, approver feedback, context chain, prior revision history.
- Output: regenerated artifact with incremented revision.
- Regenerated artifacts MUST re-enter `reviewer_queue` and follow the same gate sequence.

---

## 18. Mathematics Rendering Contract (LaTeX + Text)

For Mathematics artifacts, the platform MUST store both machine-renderable LaTeX and plain-language text forms.

### 18.1 Math Content Dual Format
Each math expression SHOULD include:
- `latex`: canonical expression for rendering.
- `text`: readable fallback expression.
- `semantic`: optional normalized math meaning.

Example:

```json
{
  "math_expression": {
    "latex": "\\frac{3x+2}{5}=7",
    "text": "(3x + 2) divided by 5 equals 7",
    "semantic": "linear_equation_single_variable"
  }
}
```

### 18.2 Question Rendering Guidance
- Inline expressions use `$...$`.
- Display equations use `$$...$$`.
- Units, symbols, and variable definitions MUST be explicit in both LaTeX and text.
- Distractors MUST preserve mathematical validity formatting.
- Marking guides SHOULD reference both symbolic and verbal reasoning steps.

### 18.3 Math Validation Rules
- LaTeX syntax must compile in selected renderer.
- Text fallback must remain pedagogically equivalent to LaTeX form.
- Reviewer and Approver must validate symbolic accuracy before approval.

---

## 19. Additional Error Codes for the Extended Workflow

| Error Code | HTTP Status | Retryable | Description |
|---|---|---|---|
| `MISSING_CONTEXT_LAYER` | 400 | No | One or more required context layers were not found. |
| `APPROVER_VERIFICATION_REQUIRED` | 412 | No | Artifact cannot be finalized before approver verification. |
| `REGENERATION_LIMIT_EXCEEDED` | 422 | No | Artifact failed after maximum regeneration attempts. |
| `HUMAN_REVIEW_REQUIRED` | 409 | No | Artifact needs human review before production state. |
| `INSUFFICIENT_WRITTEN_RESPONSE_ITEMS` | 422 | No | Generated batch does not meet minimum written-response question requirement. |

---

## 20. Model Provider, Endpoint, and Per-Pipeline Routing Contract

### 20.1 Allowed Model Providers
The runtime SHALL only allow the following provider identifiers:
- `openai`
- `anthropic`
- `gemini`
- `ollama`

Any other provider name MUST fail validation with `UNSUPPORTED_MODEL_PROVIDER`.

### 20.2 Endpoint Policy
- `openai`, `anthropic`, and `gemini` MUST use their official/recommended base URLs by default.
- `ollama` MUST support admin-configured base URL (self-hosted or remote), for example `http://localhost:11434`.
- Pipeline execution MUST resolve endpoint in this order:
  1. Pipeline-stage override (if allowed and set).
  2. Provider default configured in admin settings.
  3. Built-in official default (only for `openai`, `anthropic`, `gemini`).

If an endpoint is invalid or unreachable, request MUST fail with `MODEL_ENDPOINT_UNAVAILABLE`.

### 20.3 API Key and Credential Management
- Admin UI/module MUST support secure credential entry for each provider: OpenAI API key, Anthropic API key, Gemini API key, and optional Ollama auth token if required by deployment.
- Credentials MUST be encrypted at rest and never returned in plaintext after save.
- Runtime logs, traces, and audit payloads MUST redact credentials and authorization headers.
- Pipeline calls MUST use provider credential selected by the resolved provider for that stage.

### 20.4 Per-Pipeline Model Selection
Each pipeline stage MUST allow explicit provider+model binding:
- `notes_generation`
- `diagram_generation`
- `activity_generation`
- `question_generation`
- `reviewer_panel`
- `regeneration`

Binding schema:

```json
{
  "pipeline_stage": "question_generation",
  "provider": "gemini",
  "model": "gemini-2.5-pro",
  "base_url": "https://generativelanguage.googleapis.com"
}
```

For `ollama`, `model` MUST be explicitly selected from available local/remote Ollama models.

### 20.5 Provenance Requirement Extension
In addition to existing provenance fields, every artifact generation record MUST include:
- `pipeline_stage`
- `resolved_model_provider`
- `resolved_model_name`
- `resolved_base_url`
- `credential_ref_id` (internal non-secret identifier only)

### 20.6 Validation and Failure Codes
Add the following error semantics:
- `UNSUPPORTED_MODEL_PROVIDER` (400): Provider is not one of `openai|anthropic|gemini|ollama`.
- `MODEL_NOT_CONFIGURED_FOR_STAGE` (400): No provider/model mapping exists for requested pipeline stage.
- `MODEL_CREDENTIAL_MISSING` (401): Required API key or credential is missing for selected provider.
- `MODEL_ENDPOINT_UNAVAILABLE` (503): Provider endpoint cannot be reached or returns repeated transport failure.

