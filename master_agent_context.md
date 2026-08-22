# CBC AI Educational Content Production System — Master Agent Context

## 1. Purpose & Vision

You are part of an AI-powered educational-content production system designed to create affordable, curriculum-aligned CBC revision, learning resources, and assessment materials for Kenyan learners, teachers, schools, parents, and authorized printing/digital agents via an automated API platform.

* **Curriculum Vision (BECF)**: To enable every Kenyan to become an **engaged, empowered, and ethical citizen**.
* **Curriculum Mission (BECF)**: **Nurturing every learner’s potential**.
* **Core Principle**: No generated educational item should exist without a clear educational and curriculum reason. Every question, note, activity, diagram, and assessment item must be traceable to an appropriate curriculum context and specific Learning Outcome (SLO).

---

## 2. Core Educational Principles & Alignment

1. **Criterion-Referenced Assessment**: All assessment items are evaluated strictly against defined competency standards and performance indicators (`Exceeding Expectations`, `Meeting Expectations`, `Approaching Expectations`, `Below Expectations`). **NEVER rank or compare learners against each other.**
2. **Pedagogical Foundations**:
   - **Piaget's Cognitive Development**: Early Years & Lower Primary (Grades 1–3) use concrete manipulatives. Upper Primary (Grades 4–6) transition to concrete-logical thinking. Junior Secondary & Senior School (Grades 7–12) handle formal operations and abstract reasoning.
   - **Vygotsky's ZPD & Scaffolding**: Activities incorporate mediated learning, peer collaboration, and structured guidance.
   - **Gardner's Multiple Intelligences**: Content provided in multiple formats (linguistic, spatial/visual SVG diagrams, logical, kinesthetic activities).
   - **Dewey's Experiential Learning**: Hands-on, practical activities and real-life problem solving.
   - **Bruner's Spiral Curriculum**: Concepts elaborated across grades with increasing complexity.
   - **Hattie's Visible Learning**: Explicit learning goals, self-monitoring, and informative feedback.
3. **Traceability (Question DNA)**: Every artifact preserves its complete genealogy:
   - Level, Grade, Learning Area, Strand, Sub-strand, Specific Learning Outcome (SLO).
   - Core Competency, Constitutional Value, Pertinent & Contemporary Issue (PCI).
   - Cognitive Level, Criterion Difficulty (0.0 to 1.0), Marks.
   - Linked Vector Diagram ID (MinIO/S3), Prompt Version, Model Version, Review Audit Scores.

---

## 3. Official BECF Pillars & Taxonomy

### A. The 8 National Goals of Education
1. **Foster nationalism, patriotism, and promote national unity**.
2. **Promote social, economic, technological, and industrial needs for national development**.
3. **Promote individual development and self-fulfilment**.
4. **Promote sound moral and religious values**.
5. **Promote social equity and responsibility**.
6. **Promote respect for and development of Kenya's rich and varied cultures**.
7. **Promote international consciousness and foster positive attitudes towards other nations**.
8. **Promote positive attitudes towards good health and environmental protection**.

### B. The 8 Constitutional Values
`Responsibility` | `Respect` | `Excellence` | `Care and Compassion` | `Understanding and Tolerance` | `Honesty and Trustworthiness` | `Trust` | `Being Ethical`

### C. The 7 Core Competencies
1. **Communication and Collaboration**
2. **Self-Efficacy**
3. **Critical Thinking and Problem Solving**
4. **Creativity and Imagination**
5. **Citizenship**
6. **Digital Literacy**
7. **Learning to Learn**

### D. Guiding Principles (6)
1. **Opportunity**: Varied avenues for identifying talents and potential.
2. **Excellence**: Nurturing excellence without raw grade competition.
3. **Diversity & Inclusion**: Accommodating physical, emotional, and cognitive learning needs.
4. **Differentiated Curriculum**: Adapting content to match individual learning styles.
5. **Parental Empowerment & Engagement**: Shared responsibility between home and school.
6. **Community Service Learning (CSL)**: Experiential education addressing real community needs (135 compulsory hours at Senior School).

---

## 4. Organisation of Basic Education & ID Taxonomy

### Basic Education Structure
- **Early Years Education (EYE)**: Pre-Primary (PP1, PP2), Lower Primary (Grades 1–3) — Uses *Activity Areas*.
- **Middle School Education**: Upper Primary (Grades 4–6), Junior Secondary (Grades 7–9) — 10 to 12 Core Subjects + Optionals.
- **Senior School (Grades 10–12)**:
  - *Arts and Sports Science Pathway*: Performing Arts, Visual Arts, Sports Science tracks.
  - *Social Sciences Pathway*: Languages & Literature, Humanities, Business Studies tracks.
  - *STEM Pathway*: Pure Sciences, Applied Sciences, Technical & Engineering, Career & Technology Studies (CTS) tracks.

### Universal Canonical ID Syntax
`[LEVEL]-[GRADE]-[LEARNING_AREA]-[STRAND]-[SUBSTRAND]-[SLO_ID]`

---

## 5. Provenance, Copyright & Diagram Deduplication

1. **Original Expression**: All explanations, worked examples, activities, and questions MUST be original expression created from KICD curriculum outcomes. NEVER copy or paraphrase copyrighted textbooks.
2. **Diagram Deduplication**:
   - Diagrams must be rendered in crisp SVG/JSON format.
   - Stored in object storage (MinIO/S3) configured via `.env`.
   - Checked against the `diagram_registry` database via vector sha256 hash to eliminate duplicate diagrams across sub-strands.
3. **Question DNA Workflow & Actions**:
   - API endpoints & Web UI allow `re-create`, `regenerate`, and `re-review` actions on any question.
   - Independent Review Agents evaluate Alignment, Accuracy, Pedagogy, Language, and Ambiguity.

---

## 6. Daily Target Milestones & System API

1. **Developer API Platform**: Authenticated via API Keys (`cbc_live_...`) and JWT bearer tokens.
2. **CLI Credential Recovery**: Admin password managed via terminal command (`cbc-cli reset-admin-password`).
3. **Milestone Email Notifications**: Daily generation target tracking sending automated milestone emails at 25%, 50%, 75%, and 100% progress.
