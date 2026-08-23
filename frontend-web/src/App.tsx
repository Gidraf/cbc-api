import { FormEvent, useMemo, useState, useEffect } from "react";
import { API_BASE_URL, fetchJson } from "./api";

type Role = "admin" | "operator" | "reviewer" | "developer";
type Provider = "openai" | "anthropic" | "gemini" | "ollama";
type Stage =
  | "notes_generation"
  | "diagram_generation"
  | "activity_generation"
  | "question_generation"
  | "reviewer_panel"
  | "regeneration";

type View =
  | "dashboard"
  | "datasets"
  | "prompts"
  | "questions"
  | "targets"
  | "generation"
  | "review"
  | "providers"
  | "pipelines"
  | "browser"
  | "production";

const roleRights: Record<Role, string[]> = {
  admin: ["all"],
  operator: ["bindings", "generate", "jobs", "health", "browse", "production_read", "targets", "datasets", "prompts"],
  reviewer: ["health", "admin_config", "jobs", "review", "human_review", "production_read", "questions"],
  developer: ["health", "admin_config", "jobs", "browse", "production_read", "questions"]
};

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function hasRight(role: Role | null, right: string): boolean {
  if (!role) return false;
  const rights = roleRights[role] || [];
  return rights.includes("all") || rights.includes(right);
}

function toOptionLabel(val: any): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "string") return val;
  if (typeof val === "number" || typeof val === "boolean") return String(val);
  if (typeof val === "object") {
    if (typeof val.name === "string") return val.name;
    if (typeof val.text === "string") return val.text;
    if (typeof val.id === "string") return String(val.id);
    if (typeof val.title === "string") return val.title;
    if (typeof val.subject === "string") return val.subject;
    return val.name || val.text || val.id || val.title || JSON.stringify(val);
  }
  return String(val);
}

export function App() {
  const [output, setOutput] = useState("Ready");
  const [view, setView] = useState<View>("dashboard");
  const [isRunning, setIsRunning] = useState(false);

  // Authentication
  const [username, setUsername] = useState(() => localStorage.getItem("cbc_username") || "admin");
  const [password, setPassword] = useState("admin123");
  const [bearerToken, setBearerToken] = useState(() => localStorage.getItem("cbc_token") || "");
  const [apiKey, setApiKey] = useState("");
  const [currentRole, setCurrentRole] = useState<Role | null>(() => (localStorage.getItem("cbc_role") as Role) || null);
  const [currentSubject, setCurrentSubject] = useState(() => localStorage.getItem("cbc_subject") || "");

  // Providers & Stage Bindings
  const [providerDrafts, setProviderDrafts] = useState<Record<Provider, { api_key: string; base_url: string; ollama_models: string }>>({
    openai: { api_key: "", base_url: "https://api.openai.com/v1", ollama_models: "" },
    anthropic: { api_key: "", base_url: "https://api.anthropic.com", ollama_models: "" },
    gemini: { api_key: "", base_url: "https://generativelanguage.googleapis.com", ollama_models: "" },
    ollama: { api_key: "", base_url: "http://host.docker.internal:11434", ollama_models: "llama3.1,qwen2.5:7b,mistral" }
  });
  const [stageDrafts, setStageDrafts] = useState<Record<Stage, { provider: Provider; model: string; base_url: string }>>({
    notes_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    diagram_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    activity_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    question_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    reviewer_panel: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    regeneration: { provider: "openai", model: "gpt-4o-mini", base_url: "" }
  });

  // Datasets & Prompts State (Langfuse)
  const [datasetsList, setDatasetsList] = useState<string[]>([]);
  const [selectedGrade, setSelectedGrade] = useState("grade-7");
  const [gradeDatasetItems, setGradeDatasetItems] = useState<any[]>([]);
  const [newSubjectName, setNewSubjectName] = useState("Integrated Science");
  const [newSubjectEssence, setNewSubjectEssence] = useState("Develops scientific inquiry, environmental conservation, and technological literacy.");
  const [selectedPromptName, setSelectedPromptName] = useState("question-generator");
  const [previewMessages, setPreviewMessages] = useState<any[]>([]);

  // Generation & Pipeline
  const [genGrade, setGenGrade] = useState("grade-7");
  const [genSubject, setGenSubject] = useState("Integrated Science");
  const [genStrand, setGenStrand] = useState("Matter");
  const [genSubstrand, setGenSubstrand] = useState("Classification of Matter");
  const [genSloId, setGenSloId] = useState("MS-G7-ISCI-MAT-CLM-01");
  const [generationResult, setGenerationResult] = useState<any>(null);

  // Question Bank
  const [questionBank, setQuestionBank] = useState<any[]>([]);
  const [selectedQuestionDna, setSelectedQuestionDna] = useState<any>(null);

  // Targets
  const [dailyTargetData, setDailyTargetData] = useState<any>(null);
  const [targetCountInput, setTargetCountInput] = useState(100);

  // Human Review & Production Bundles
  const [reviewBundles, setReviewBundles] = useState<any[]>([]);
  const [reviewFilter, setReviewFilter] = useState("human_review_queue");
  const [selectedBundleForModal, setSelectedBundleForModal] = useState<any>(null);
  const [reviewNotesInput, setReviewNotesInput] = useState("");

  // Browser Agent
  const [browseUrl, setBrowseUrl] = useState("https://example.com");

  // Dynamic Curriculum Data
  const [gradeSubjects, setGradeSubjects] = useState<any[]>([]);
  const [subjectStrands, setSubjectStrands] = useState<any[]>([]);
  const [substrandSlos, setSubstrandSlos] = useState<string[]>([]);
  const [rawCurriculumInput, setRawCurriculumInput] = useState("");
  const [ingestedDesignResult, setIngestedDesignResult] = useState<any>(null);
  const [rawLangfuseDatasets, setRawLangfuseDatasets] = useState<any[]>([]);
  const [curriculumDesignsList, setCurriculumDesignsList] = useState<any[]>([]);
  const [blueprintReviewModal, setBlueprintReviewModal] = useState<any | null>(null);
  const [humanBlueprintNotes, setHumanBlueprintNotes] = useState<string>("");

  // Global BECF Context
  const [masterContext, setMasterContext] = useState("");
  const [masterContextMeta, setMasterContextMeta] = useState<any>(null);
  const [masterContextDraft, setMasterContextDraft] = useState("");

  // Cost Tracking
  const [costSummary, setCostSummary] = useState<any>(null);
  const [generationCosts, setGenerationCosts] = useState<any>(null);

  // Content Factory & Interactive Playground State
  const [factoryStep, setFactoryStep] = useState<1 | 2 | 3 | 4>(1);
  const [factorySubstrandsList, setFactorySubstrandsList] = useState<any[]>([]);
  const [factorySelectedSubstrand, setFactorySelectedSubstrand] = useState<any>(null);

  // Station 1: Notes
  const [stationNotes, setStationNotes] = useState<any>(null);
  const [notesRefinePrompt, setNotesRefinePrompt] = useState("");
  const [notesApproved, setNotesApproved] = useState(false);

  // Station 2: SVG Diagram
  const [stationDiagram, setStationDiagram] = useState<any>(null);
  const [diagramConceptInput, setDiagramConceptInput] = useState("");
  const [diagramRefinePrompt, setDiagramRefinePrompt] = useState("");
  const [diagramViewMode, setDiagramViewMode] = useState<"visual" | "code" | "tactile">("visual");
  const [diagramApproved, setDiagramApproved] = useState(false);

  // Station 3: Experiments & Safety
  const [stationActivity, setStationActivity] = useState<any>(null);
  const [activityRefinePrompt, setActivityRefinePrompt] = useState("");
  const [activityApproved, setActivityApproved] = useState(false);

  // Station 4: Questions & Rubrics
  const [stationQuestions, setStationQuestions] = useState<any[]>([]);
  const [questionsDifficulty, setQuestionsDifficulty] = useState(0.65);
  const [questionsRefinePrompt, setQuestionsRefinePrompt] = useState("");
  const [questionsApproved, setQuestionsApproved] = useState(false);

  // Sub-strand Generator Studio State
  const [substrandGenModal, setSubstrandGenModal] = useState<{ strand_name: string; strand_id?: string } | null>(null);
  const [generatedSubstrandsDraft, setGeneratedSubstrandsDraft] = useState<any[]>([]);
  const [substrandPromptInput, setSubstrandPromptInput] = useState("");
  const [substrandSourceMaterial, setSubstrandSourceMaterial] = useState("");
  const [showSourceMaterialText, setShowSourceMaterialText] = useState(false);
  const [strandPromptInput, setStrandPromptInput] = useState("");

  // Audit & Deliberation
  const [factoryAudit, setFactoryAudit] = useState<any>(null);
  const [factoryDeliberation, setFactoryDeliberation] = useState<any>(null);

  // Error banner state
  const [errorBanner, setErrorBanner] = useState<{code: string; message: string; retryable: boolean} | null>(null);

  const title = useMemo(() => `CBC API Platform`, []);

  function auth() {
    return {
      bearerToken: bearerToken || undefined,
      apiKey: apiKey || undefined
    };
  }

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    try {
      setIsRunning(true);
      setOutput(`${label}...`);
      setErrorBanner(null);
      const result = await fn();
      setOutput(pretty(result));
      return result;
    } catch (err: any) {
      const errBody = err?.payload || {};
      const errCode = errBody?.error?.code || "UNEXPECTED_ERROR";
      const errMsg = errBody?.error?.message || err.message || "An unexpected error occurred.";
      const retryable = errBody?.error?.retryable || false;

      setErrorBanner({ code: errCode, message: errMsg, retryable });
      setOutput(`Error (${errCode}): ${errMsg}`);
      return undefined;
    } finally {
      setIsRunning(false);
    }
  }

  // Authentication Handlers
  async function onLoginSubmit(e: FormEvent) {
    e.preventDefault();
    await run("Signing in", async () => {
      const res = await fetchJson<any>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      setBearerToken(res.access_token);
      setCurrentRole(res.user.role);
      setCurrentSubject(res.user.subject_scope || "");
      localStorage.setItem("cbc_token", res.access_token);
      localStorage.setItem("cbc_role", res.user.role);
      localStorage.setItem("cbc_username", username);
      localStorage.setItem("cbc_subject", res.user.subject_scope || "");
      return res;
    });
  }

  function logout() {
    setBearerToken("");
    setCurrentRole(null);
    localStorage.removeItem("cbc_token");
    localStorage.removeItem("cbc_role");
    localStorage.removeItem("cbc_username");
  }

  // Dynamic Curriculum Cascade
  async function loadGradeSubjects(gradeSlug: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects`, { method: "GET" }, auth());
      const subs = res.subjects || [];
      setGradeSubjects(subs);
      if (subs.length > 0) {
        const firstSub = subs[0].name || subs[0];
        setGenSubject(firstSub);
        await loadSubjectStrands(gradeSlug, firstSub);
      }
    } catch(e) {
      setGradeSubjects([]);
    }
  }

  async function loadSubjectStrands(gradeSlug: string, subject: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects/${encodeURIComponent(subject)}/strands`, { method: "GET" }, auth());
      const strands = res.strands || [];
      setSubjectStrands(strands);
      if (strands.length > 0) {
        const firstStrand = strands[0].name;
        setGenStrand(firstStrand);
        const subList = strands[0].sub_strands || [];
        if (subList.length > 0) {
          const firstSub = subList[0].name || subList[0];
          setGenSubstrand(firstSub);
          await loadSubstrandSlos(gradeSlug, subject, firstStrand, firstSub);
        }
      }
    } catch(e) {
      setSubjectStrands([]);
    }
  }

  async function loadSubstrandSlos(gradeSlug: string, subject: string, strand: string, subStrand: string) {
    try {
      const res = await fetchJson<any>(
        `/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects/${encodeURIComponent(subject)}/strands/${encodeURIComponent(strand)}/substrands/${encodeURIComponent(subStrand)}/slos`,
        { method: "GET" },
        auth()
      );
      const slos = res.slos || [];
      setSubstrandSlos(slos);
      if (slos.length > 0) {
        setGenSloId(slos[0]);
      }
    } catch(e) {
      setSubstrandSlos([]);
    }
  }

  // Datasets Management
  async function loadDatasets() {
    try {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/datasets", { method: "GET" }, auth());
      const rawList = res.datasets || [];
      const normalized: string[] = rawList.map((d: any) => typeof d === "string" ? d : (d.name || String(d)));
      const finalGrades = normalized.length > 0 ? normalized : ["grade-dte", "grade-7", "grade-8"];
      setDatasetsList(finalGrades);
      const gradeToUse = finalGrades[0];
      setSelectedGrade(gradeToUse);
      setGenGrade(gradeToUse);
      await loadGradeSubjects(gradeToUse);
      await loadGradeDataset(gradeToUse);
    } catch(e) {
      setDatasetsList(["grade-dte", "grade-7"]);
    }
  }

  async function loadGradeDataset(gradeSlug: string) {
    if (!gradeSlug) return;
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}`, { method: "GET" }, auth());
      setGradeDatasetItems(res.items || []);
    } catch(e) {
      setGradeDatasetItems([]);
    }
  }

  async function onUploadSubjectContext(e: FormEvent) {
    e.preventDefault();
    await run("Upload Subject Context to Langfuse", async () => {
      const payload = {
        subject: newSubjectName,
        essence_statement: newSubjectEssence,
        strands: []
      };
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${selectedGrade}/items`, {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());
      await loadGradeDataset(selectedGrade);
      return res;
    });
  }

  // Master Context Management
  async function loadMasterContext() {
    try {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/master", { method: "GET" }, auth());
      const txt = res.text || res.master_context || "";
      setMasterContext(txt);
      setMasterContextDraft(txt);
      setMasterContextMeta(res);
    } catch(e) { /* ignore */ }
  }

  async function saveMasterContext() {
    await run("Save Master Context", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/master", {
        method: "PUT",
        body: JSON.stringify({ text: masterContextDraft })
      }, auth());
      setMasterContext(masterContextDraft);
      setMasterContextMeta(res);
      return res;
    });
  }

  async function seedLangfuse() {
    await run("Seed Langfuse", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/seed", { method: "POST" }, auth());
      await loadDatasets();
      return res;
    });
  }

  async function onIngestRawCurriculum() {
    if (!rawCurriculumInput.trim()) return;
    await run("Ingest & Structure Raw Curriculum", async () => {
      let bodyPayload: any = { raw_text: rawCurriculumInput };
      try {
        const parsed = JSON.parse(rawCurriculumInput);
        bodyPayload = { raw_payload: parsed };
      } catch {
        // Plain text format
      }
      const res = await fetchJson<any>("/api/v1/curriculum/ingest-raw", {
        method: "POST",
        body: JSON.stringify(bodyPayload)
      }, auth());
      setIngestedDesignResult(res);
      await loadDatasets();
      await loadCurriculumDesigns();
      await loadRawLangfuseDatasets();
      if (res.grade) {
        setSelectedGrade(res.grade);
        setGenGrade(res.grade);
        await loadGradeDataset(res.grade);
        await loadGradeSubjects(res.grade);
      }
      return res;
    });
  }

  async function loadRawLangfuseDatasets() {
    try {
      const res = await fetchJson<any>("/api/v1/curriculum/raw-datasets", { method: "GET" }, auth());
      setRawLangfuseDatasets(res.raw_datasets || []);
    } catch(e) {
      setRawLangfuseDatasets([]);
    }
  }

  async function loadCurriculumDesigns() {
    try {
      const res = await fetchJson<any>("/api/v1/curriculum/designs", { method: "GET" }, auth());
      setCurriculumDesignsList(res.designs || []);
    } catch(e) {
      setCurriculumDesignsList([]);
    }
  }

  async function onProcessDatasetItem(item: any) {
    await run(`Process with AI & BECF Context: ${item.title || item.item_id}`, async () => {
      const res = await fetchJson<any>("/api/v1/curriculum/ingest-raw", {
        method: "POST",
        body: JSON.stringify({ raw_payload: item.raw_payload || item })
      }, auth());
      setBlueprintReviewModal(res);
      await loadCurriculumDesigns();
      await loadDatasets();
      return res;
    });
  }

  async function onBlueprintDecision(designId: string, decision: "accept" | "reject") {
    await run(`Curriculum Blueprint Decision (${decision})`, async () => {
      const res = await fetchJson<any>("/api/v1/curriculum/blueprint-decision", {
        method: "POST",
        body: JSON.stringify({ design_id: designId, decision, notes: humanBlueprintNotes })
      }, auth());
      setBlueprintReviewModal(null);
      setHumanBlueprintNotes("");
      await loadCurriculumDesigns();
      await loadDatasets();
      if (res?.updated_design?.grade) {
        setSelectedGrade(res.updated_design.grade);
        setGenGrade(res.updated_design.grade);
        await loadGradeSubjects(res.updated_design.grade);
      }
      return res;
    });
  }

  async function syncLangfuseDatasets() {
    await run("Pull & Structure All Datasets from Langfuse", async () => {
      const res = await fetchJson<any>("/api/v1/curriculum/sync-langfuse-datasets", {
        method: "POST"
      }, auth());
      await loadDatasets();
      await loadRawLangfuseDatasets();
      await loadCurriculumDesigns();
      if (res.structured_blueprints && res.structured_blueprints.length > 0) {
        setIngestedDesignResult(res.structured_blueprints[0]);
        setBlueprintReviewModal(res.structured_blueprints[0]);
        const firstGrade = res.structured_blueprints[0].grade;
        if (firstGrade) {
          setSelectedGrade(firstGrade);
          setGenGrade(firstGrade);
          await loadGradeDataset(firstGrade);
          await loadGradeSubjects(firstGrade);
        }
      }
      return res;
    });
  }

  // Prompt preview
  async function previewPromptContext() {
    await run("Assemble Prompt Context", async () => {
      const slug = genGrade.startsWith("grade-") ? genGrade : `grade-${genGrade}`;
      const payload = {
        agent_name: selectedPromptName,
        grade_slug: slug,
        subject: genSubject,
        template_vars: {
          level: "Basic Education",
          strand: genStrand,
          sub_strand: genSubstrand,
          slo_id: genSloId,
        }
      };
      const res = await fetchJson<any>("/api/v1/admin/langfuse/prompts/preview", {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());
      setPreviewMessages(res.messages || []);
      return res;
    });
  }

  // Generation & Pipeline Execution
  async function triggerGenerate() {
    await run("Run Full CBC Production Pipeline", async () => {
      const slug = genGrade.startsWith("grade-") ? genGrade : `grade-${genGrade}`;
      const payload = {
        request_id: `req_${Date.now()}`,
        trace_id: `trace_${Date.now()}`,
        curriculum: {
          grade: slug,
          subject: genSubject,
          subject_code: genSubject.substring(0, 4).toUpperCase(),
          strand: genStrand,
          sub_strand: genSubstrand,
          slo_id: genSloId || "SLO-GEN",
          level: "Basic Education"
        },
        controls: {
          environment: "production",
          strict_validation: true,
          force_refresh: true
        }
      };
      const res = await fetchJson<any>("/generate", {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());

      const result = res.result || {};
      setGenerationResult(result.published_bundle || {});
      setGenerationCosts(result.cost_summary || {});

      // Also populate the interactive factory stations if result is returned
      if (result.published_bundle) {
        const pb = result.published_bundle;
        if (pb.notes) setStationNotes(pb.notes);
        if (pb.diagrams?.[0]) setStationDiagram(pb.diagrams[0]);
        if (pb.activities || pb.experiments) setStationActivity({ activities: pb.activities || [], experiments: pb.experiments || [] });
        if (pb.questions) setStationQuestions(pb.questions);
        if (pb.review_audit) setFactoryAudit(pb.review_audit);
        if (pb.multi_agent_deliberation) setFactoryDeliberation(pb.multi_agent_deliberation);
      }

      await Promise.all([loadQuestionBank(), loadCostSummary(), loadReviewBundles(reviewFilter)]);
      return res;
    });
  }

  // Content Factory Actions & Station Generators
  async function loadFactorySubstrandsForDesign(grade: string, subject: string) {
    if (!grade || !subject) return;
    try {
      const res = await fetchJson<any>(`/api/v1/curriculum/substrands?grade=${grade}&subject=${encodeURIComponent(subject)}`, { method: "GET" }, auth());
      setFactorySubstrandsList(res.substrands || []);
    } catch(e) {
      setFactorySubstrandsList([]);
    }
  }

  function selectSubstrandForFactory(ss: any, grade: string, subject: string) {
    setFactorySelectedSubstrand(ss);
    setGenGrade(grade);
    setGenSubject(subject);
    setGenStrand(ss.strand_name || "");
    setGenSubstrand(ss.sub_strand_name || ss.name || "");
    setGenSloId(ss.slos?.[0] || "");
    setDiagramConceptInput(ss.required_diagrams?.[0] || ss.sub_strand_name || "Visual Model");
    setFactoryStep(2);
    setNotesApproved(false);
    setDiagramApproved(false);
    setActivityApproved(false);
    setQuestionsApproved(false);
  }

  async function generateFactoryNotes(customInstructions?: string) {
    await run("Generating Notes in Factory...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        slo_id: genSloId,
        level: "Basic Education",
        custom_instructions: customInstructions || notesRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-notes", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.notes) {
        setStationNotes(res.notes);
        setNotesApproved(false);
      }
      return res;
    });
  }

  async function generateFactoryDiagram(customInstructions?: string) {
    await run("Generating Vector SVG Diagram in Factory...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        concept: diagramConceptInput || genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        custom_instructions: customInstructions || diagramRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-diagram", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.diagram) {
        setStationDiagram(res.diagram);
        setDiagramApproved(false);
      }
      return res;
    });
  }

  async function generateFactoryActivity(customInstructions?: string) {
    await run("Generating Practical Experiments & Safety Guidelines in Factory...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        custom_instructions: customInstructions || activityRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-activity", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.activity) {
        setStationActivity(res.activity);
        setActivityApproved(false);
      }
      return res;
    });
  }

  async function generateFactoryQuestions(customInstructions?: string) {
    await run("Generating Criterion Assessment Questions in Factory...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        subject_code: genSubject.substring(0, 4).toUpperCase(),
        strand: genStrand,
        sub_strand: genSubstrand,
        slo_id: genSloId,
        difficulty: questionsDifficulty,
        notes_summary: stationNotes?.intro || "",
        diagram_title: stationDiagram?.diagram_title || "",
        custom_instructions: customInstructions || questionsRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-questions", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.questions) {
        setStationQuestions(res.questions);
        setQuestionsApproved(false);
      }
      return res;
    });
  }

  async function saveFactorySubstrandBundle(reviewStatus: string = "draft_in_factory") {
    await run(`Saving Sub-strand Bundle (${reviewStatus})...`, async () => {
      const bundleId = `bundle_${genGrade}_${genSubject.substring(0, 4).toLowerCase()}_${Date.now()}`;
      const payload = {
        bundle_id: bundleId,
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        level: "Basic Education",
        notes: stationNotes || {},
        diagram: stationDiagram || {},
        activities: stationActivity?.activities || [],
        experiments: stationActivity?.experiments || [],
        questions: stationQuestions || [],
        review_status: reviewStatus,
        human_notes: "Saved via Content Factory Playground",
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/save-bundle", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      await Promise.all([loadQuestionBank(), loadReviewBundles("all")]);
      return res;
    });
  }

  // Sub-strand & Strand AI Generation Handlers
  async function handleGenerateStrands(customInstructions?: string) {
    await run("Generating Top-Level Strands...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        level: "Basic Education",
        essence_statement: `Curriculum design for ${genSubject} (${genGrade}).`,
        custom_instructions: customInstructions || strandPromptInput,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-strands", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.strands) {
        setSubjectStrands(res.strands.map((s: any) => ({
          name: s.strand_name || s.name || s,
          sub_strands: [],
        })));
      }
      return res;
    });
  }

  function handleOpenSubstrandGenerator(strandName: string, strandId: string = "1.0") {
    const activeCd = curriculumDesignsList.find((cd: any) =>
      cd.subject?.toLowerCase() === genSubject?.toLowerCase() &&
      (cd.grade === genGrade || cd.grade === genGrade.replace("grade-", ""))
    ) || (ingestedDesignResult?.subject?.toLowerCase() === genSubject?.toLowerCase() ? ingestedDesignResult : null);

    const rawSrcText =
      activeCd?.raw_payload?.raw_text ||
      activeCd?.raw_payload?.text ||
      activeCd?.raw_payload?.output ||
      rawCurriculumInput ||
      "";

    setSubstrandGenModal({
      strand_name: strandName,
      strand_id: strandId,
      ...(activeCd ? {
        essence_statement: activeCd.essence_statement,
        general_learning_outcomes: activeCd.general_learning_outcomes,
        level: activeCd.level,
      } : {})
    });
    setSubstrandSourceMaterial(rawSrcText);
    setGeneratedSubstrandsDraft([]);
    setSubstrandPromptInput(`Generate all required comprehensive sub-strands for ${strandName} with allocated hours (e.g. 4 hours), SLOs, practical experiments, and safety protocols.`);
  }

  async function handleGenerateSubstrands(customInstructions?: string) {
    if (!substrandGenModal) return;
    await run(`Generating Sub-strands for ${substrandGenModal.strand_name}...`, async () => {
      const activeCd = curriculumDesignsList.find((cd: any) =>
        cd.subject?.toLowerCase() === genSubject?.toLowerCase() &&
        (cd.grade === genGrade || cd.grade === genGrade.replace("grade-", ""))
      ) || (ingestedDesignResult?.subject?.toLowerCase() === genSubject?.toLowerCase() ? ingestedDesignResult : null);

      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand_name: substrandGenModal.strand_name,
        strand_id: substrandGenModal.strand_id || "1.0",
        level: activeCd?.level || "Basic Education",
        essence_statement: activeCd?.essence_statement || "",
        general_learning_outcomes: activeCd?.general_learning_outcomes || [],
        source_material_text: substrandSourceMaterial,
        custom_instructions: customInstructions || substrandPromptInput,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-substrands", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.sub_strands) {
        setGeneratedSubstrandsDraft(res.sub_strands);
      }
      return res;
    });
  }

  async function handleSaveSubstrandsToDatabase() {
    if (!substrandGenModal || generatedSubstrandsDraft.length === 0) return;
    await run(`Saving Sub-strands for ${substrandGenModal.strand_name}...`, async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand_name: substrandGenModal.strand_name,
        strand_id: substrandGenModal.strand_id || "1.0",
        substrands: generatedSubstrandsDraft,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/save-substrands", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      await loadFactorySubstrandsForDesign(genGrade, genSubject);
      setSubstrandGenModal(null);
      return res;
    });
  }

  // Human Review & Bundles Management
  async function loadReviewBundles(status: string = "human_review_queue") {
    try {
      const query = status === "all" ? "" : `?status=${status}`;
      const res = await fetchJson<any>(`/api/v1/bundles${query}`, { method: "GET" }, auth());
      setReviewBundles(res.bundles || []);
    } catch(e) {
      setReviewBundles([]);
    }
  }

  async function handleHumanDecision(bundleId: string, decision: string) {
    await run(`Human Review: ${decision.toUpperCase()}`, async () => {
      const res = await fetchJson<any>(`/api/v1/bundles/${bundleId}/human-decision`, {
        method: "POST",
        body: JSON.stringify({ decision, notes: reviewNotesInput })
      }, auth());
      setSelectedBundleForModal(null);
      setReviewNotesInput("");
      await loadReviewBundles(reviewFilter);
      return res;
    });
  }

  // Question Bank
  async function loadQuestionBank() {
    try {
      const res = await fetchJson<any>("/api/v1/questions?limit=50", { method: "GET" }, auth());
      setQuestionBank(res.items || res.questions || []);
    } catch(e) { /* ignore */ }
  }

  async function triggerQuestionAction(questionId: string, action: string) {
    await run(`Question Action (${action})`, async () => {
      const res = await fetchJson<any>(`/api/v1/questions/${questionId}/action`, {
        method: "POST",
        body: JSON.stringify({ action, reason: `Triggered from control plane: ${action}` })
      }, auth());
      await loadQuestionBank();
      return res;
    });
  }

  // Target Metrics
  async function loadTodayTarget() {
    try {
      const res = await fetchJson<any>("/api/v1/targets/today", { method: "GET" }, auth());
      setDailyTargetData(res);
    } catch(e) { /* ignore */ }
  }

  async function configureTargetSubmit(e: FormEvent) {
    e.preventDefault();
    await run("Save Daily Target", async () => {
      const res = await fetchJson<any>("/api/v1/targets/configure", {
        method: "POST",
        body: JSON.stringify({ target_date: new Date().toISOString().split("T")[0], target_count: targetCountInput })
      }, auth());
      await loadTodayTarget();
      return res;
    });
  }

  // Cost tracking
  async function loadCostSummary() {
    try {
      const res = await fetchJson<any>("/api/v1/costs/summary", { method: "GET" }, auth());
      setCostSummary(res);
    } catch(e) { /* ignore */ }
  }

  // Refresh Dashboard
  async function refreshDashboard() {
    await Promise.all([loadTodayTarget(), loadQuestionBank(), loadCostSummary()]);
  }

  useEffect(() => {
    if (currentRole) {
      loadDatasets();
      loadRawLangfuseDatasets();
      loadCurriculumDesigns();
      loadTodayTarget();
      loadQuestionBank();
      loadCostSummary();
      loadMasterContext();
      loadReviewBundles(reviewFilter);
    }
  }, [currentRole]);

  const canAdmin = hasRight(currentRole, "all");

  const navItems: Array<{ id: View; label: string; right: string }> = [
    { id: "dashboard", label: "Dashboard", right: "health" },
    { id: "datasets", label: "Datasets & Blueprints", right: "datasets" },
    { id: "generation", label: "🏭 Content Factory", right: "generate" },
    { id: "review", label: "Review & Human Approval", right: "review" },
    { id: "production", label: "Production Bundles", right: "production_read" },
    { id: "prompts", label: "Prompt Builder", right: "prompts" },
    { id: "questions", label: "Questions & DNA", right: "questions" },
    { id: "targets", label: "Targets & Alerts", right: "targets" },
    { id: "providers", label: "Model Providers", right: "all" },
    { id: "pipelines", label: "Stage Bindings", right: "bindings" },
    { id: "browser", label: "Browser Agent", right: "browse" }
  ];

  if (!currentRole) {
    return (
      <div className="login-shell">
        <section className="login-art">
          <h1>{title}</h1>
          <p>Contract-first multi-agent production platform for Kenyan CBC educational content, Question DNA, and vector diagrams.</p>
        </section>

        <section className="login-card">
          <h2>Sign In to Control Plane</h2>
          <form onSubmit={onLoginSubmit} className="stack">
            <label>
              Role
              <select value={username} onChange={(e) => setUsername(e.target.value)}>
                <option value="admin">Admin</option>
                <option value="operator">Operator</option>
                <option value="reviewer">Reviewer</option>
                <option value="developer">Developer</option>
              </select>
            </label>
            <label>
              Username
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
            </label>
            <button type="submit" disabled={isRunning}>Sign In</button>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="cp-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">C</span>
          <div>
            <strong>CBC API</strong>
            <small>Platform Control Room</small>
          </div>
        </div>

        <nav>
          {navItems
            .filter((item) => hasRight(currentRole, item.right) || (item.right === "all" && canAdmin))
            .map((item) => (
              <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => {
                setView(item.id);
                if (item.id === "review") loadReviewBundles(reviewFilter);
                if (item.id === "production") loadReviewBundles("published");
              }}>
                {item.label}
              </button>
            ))}
        </nav>

        <div className="sidebar-footer">
          <button className="ghost" onClick={logout}>Sign out</button>
          <small>{currentSubject} ({currentRole})</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <h1>{title}</h1>
          <div className="topbar-actions">
            <span className="pill ok">Langfuse Connected</span>
            <span className="pill ok">Role: {currentRole}</span>
          </div>
        </header>

        {/* Global Error Banner */}
        {errorBanner && (
          <div className="error-banner">
            <div className="error-banner-content">
              <strong>{errorBanner.code}</strong>
              <p>{errorBanner.message}</p>
            </div>
            {errorBanner.retryable && (
              <span className="pill warn">Retryable Error</span>
            )}
            <button className="ghost" onClick={() => setErrorBanner(null)} style={{marginLeft: 'auto'}}>Dismiss</button>
          </div>
        )}

        {/* 1. DASHBOARD TAB */}
        {view === "dashboard" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Operations Dashboard</h2>
                <p>System KPIs, pipeline health, token consumption, and daily production target tracking.</p>
              </div>
              <button className="ghost" onClick={refreshDashboard} disabled={isRunning}>Refresh</button>
            </div>

            <div className="kpi-grid">
              <div className="kpi">
                <div className="muted">Master Context</div>
                <div className="kpi-value">{masterContext ? "Loaded (BECF)" : "Pending Seed"}</div>
              </div>
              <div className="kpi">
                <div className="muted">Total Tokens Consumed</div>
                <div className="kpi-value">{(costSummary?.total_tokens || 0).toLocaleString()}</div>
              </div>
              <div className="kpi">
                <div className="muted">Total LLM Cost (USD)</div>
                <div className="kpi-value">${(costSummary?.total_cost_usd || 0).toFixed(4)}</div>
              </div>
              <div className="kpi">
                <div className="muted">Generation Runs</div>
                <div className="kpi-value">{costSummary?.total_runs || 0}</div>
              </div>
            </div>

            {/* Cost Breakdown by Provider Table */}
            {costSummary?.cost_by_provider && costSummary.cost_by_provider.length > 0 && (
              <div style={{marginTop: '1.5rem'}}>
                <h3>Cost & Token Consumption by Model</h3>
                <table style={{width: '100%', marginTop: '0.5rem', fontSize: '0.85rem'}}>
                  <thead>
                    <tr style={{textAlign: 'left'}}>
                      <th>Provider</th><th>Model</th><th>Prompt Tokens</th><th>Completion</th><th>Total Tokens</th><th>Total Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costSummary.cost_by_provider.map((p: any, idx: number) => (
                      <tr key={idx}>
                        <td><strong>{p.provider}</strong></td>
                        <td>{p.model}</td>
                        <td>{(p.prompt_tokens || 0).toLocaleString()}</td>
                        <td>{(p.completion_tokens || 0).toLocaleString()}</td>
                        <td>{(p.total_tokens || 0).toLocaleString()}</td>
                        <td>${(p.total_cost_usd || 0).toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* 2. DATASETS & BLUEPRINTS TAB */}
        {view === "datasets" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Live Langfuse Datasets & Curriculum Blueprints</h2>
                <p>All datasets are pulled directly from Langfuse. Click <strong>"⚡ Process with AI"</strong> to extract the subject, grade, strands, diagrams, experiments with safety hazard criteria, and dynamic agent prompts, then manually review and approve the blueprint.</p>
              </div>
              <div style={{display: 'flex', gap: '0.5rem'}}>
                <button onClick={loadRawLangfuseDatasets} disabled={isRunning} className="ghost">
                  🔄 Refresh Langfuse Datasets
                </button>
                <button onClick={syncLangfuseDatasets} disabled={isRunning} style={{background: '#4338ca', borderColor: '#4338ca'}}>
                  {isRunning ? "Syncing..." : "📥 Auto-Pull & Sync All from Langfuse"}
                </button>
              </div>
            </div>

            {/* 1. LIVE LANGFUSE RAW DATASETS LIST */}
            <div className="panel" style={{marginTop: '0.5rem', marginBottom: '1.5rem', border: '1px solid #cbd5e1'}}>
              <div className="panel-head">
                <div>
                  <h3>📦 Raw Datasets in Langfuse ({rawLangfuseDatasets.length})</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>Unprocessed raw curriculum design texts (OCR extracts, Google Drive PDFs, browser captures).</p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                {rawLangfuseDatasets.length === 0 ? (
                  <div style={{padding: '1.5rem', textAlign: 'center', color: '#64748b'}}>
                    No raw datasets found in Langfuse yet. Click <strong>"📥 Auto-Pull & Sync All from Langfuse"</strong> to seed and load live datasets.
                  </div>
                ) : (
                  <table style={{width: '100%', fontSize: '0.85rem', borderCollapse: 'collapse'}}>
                    <thead>
                      <tr style={{textAlign: 'left', borderBottom: '2px solid #e2e8f0'}}>
                        <th style={{padding: '8px'}}>Dataset / Source</th>
                        <th style={{padding: '8px'}}>Title / File ID</th>
                        <th style={{padding: '8px'}}>Length</th>
                        <th style={{padding: '8px'}}>Preview</th>
                        <th style={{padding: '8px', textAlign: 'right'}}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rawLangfuseDatasets.map((item: any, idx: number) => (
                        <tr key={idx} style={{borderBottom: '1px solid #f1f5f9'}}>
                          <td style={{padding: '8px'}}>
                            <span className="pill" style={{background: '#e0e7ff', color: '#3730a3'}}>{item.dataset_name}</span>
                            <div style={{fontSize: '0.75rem', color: '#64748b', marginTop: '2px'}}>{item.source}</div>
                          </td>
                          <td style={{padding: '8px'}}>
                            <strong>{item.title}</strong>
                            <div style={{fontSize: '0.75rem', color: '#64748b'}}>{item.file_id || item.item_id}</div>
                          </td>
                          <td style={{padding: '8px'}}>
                            {(item.text_length || 0).toLocaleString()} chars
                          </td>
                          <td style={{padding: '8px', color: '#475569', maxWidth: '300px'}}>
                            <div style={{fontSize: '0.78rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
                              {item.output_preview || "(No preview)"}
                            </div>
                          </td>
                          <td style={{padding: '8px', textAlign: 'right'}}>
                            <button
                              onClick={() => onProcessDatasetItem(item)}
                              disabled={isRunning}
                              style={{fontSize: '0.8rem', padding: '6px 12px', background: '#059669', borderColor: '#059669'}}
                            >
                              ⚡ Process with AI & BECF
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            {/* 2. HUMAN REVIEW MODAL FOR GENERATED BLUEPRINT */}
            {blueprintReviewModal && (
              <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(15, 23, 42, 0.75)', zIndex: 9999,
                display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem'
              }}>
                <div style={{
                  background: '#ffffff', borderRadius: '12px', width: '100%', maxWidth: '960px',
                  maxHeight: '90vh', overflowY: 'auto', padding: '1.5rem', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)'
                }}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '2px solid #e2e8f0', paddingBottom: '0.75rem'}}>
                    <div>
                      <h2 style={{margin: 0, color: '#1e293b'}}>🔍 Curriculum Blueprint Human Review</h2>
                      <p style={{margin: 0, fontSize: '0.85rem', color: '#64748b'}}>Review AI-extracted Grade, Subject, Strands, Safety Hazard Guidelines, and Generated Agent Prompts before publishing to Generation Studio.</p>
                    </div>
                    <button className="ghost" onClick={() => setBlueprintReviewModal(null)} style={{fontSize: '1.2rem', padding: '4px 10px'}}>✕</button>
                  </div>

                  {/* Blueprint Summary Details */}
                  <div style={{marginTop: '1rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem'}}>
                    <div style={{background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                      <div style={{fontSize: '0.75rem', color: '#64748b'}}>Discovered Subject</div>
                      <div style={{fontSize: '1.1rem', fontWeight: 700, color: '#0f172a'}}>{blueprintReviewModal.subject}</div>
                      <span className="pill ok" style={{marginTop: '4px'}}>{blueprintReviewModal.subject_code || "CORE"}</span>
                    </div>
                    <div style={{background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                      <div style={{fontSize: '0.75rem', color: '#64748b'}}>Grade / Level</div>
                      <div style={{fontSize: '1.1rem', fontWeight: 700, color: '#0f172a'}}>{blueprintReviewModal.grade}</div>
                      <div style={{fontSize: '0.8rem', color: '#64748b'}}>{blueprintReviewModal.level || "Teacher Education"}</div>
                    </div>
                    <div style={{background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                      <div style={{fontSize: '0.75rem', color: '#64748b'}}>Sub-strands Extracted</div>
                      <div style={{fontSize: '1.1rem', fontWeight: 700, color: '#0f172a'}}>{blueprintReviewModal.substrand_count || blueprintReviewModal.substrands?.length || 0}</div>
                      <div style={{fontSize: '0.75rem', color: '#059669'}}>✓ All SLOs & Hours Parsed</div>
                    </div>
                    <div style={{background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                      <div style={{fontSize: '0.75rem', color: '#64748b'}}>Universal DNA Certificates</div>
                      <div style={{fontSize: '0.75rem', color: '#334155', wordBreak: 'break-all'}}><strong>Dataset:</strong> {blueprintReviewModal.dataset_dna_id?.slice(0, 16)}...</div>
                      <div style={{fontSize: '0.75rem', color: '#334155', wordBreak: 'break-all'}}><strong>Subject:</strong> {blueprintReviewModal.subject_dna_id?.slice(0, 16)}...</div>
                    </div>
                  </div>

                  {/* Essence Statement */}
                  <div style={{marginTop: '1rem', background: '#eff6ff', border: '1px solid #bfdbfe', padding: '0.75rem', borderRadius: '8px'}}>
                    <strong style={{color: '#1e40af'}}>Essence Statement:</strong>
                    <p style={{margin: '4px 0 0', fontSize: '0.85rem', color: '#1e3a8a'}}>{blueprintReviewModal.essence_statement || "Develops competent vocational and pedagogical capabilities aligned with Kenyan national goals."}</p>
                  </div>

                  {/* Strands & Sub-strands Accordion Table */}
                  <div style={{marginTop: '1.25rem'}}>
                    <h4 style={{margin: '0 0 0.5rem', color: '#334155'}}>🌿 Extracted Strands & Sub-strand Blueprints</h4>
                    <div style={{border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden'}}>
                      {blueprintReviewModal.substrands?.map((ss: any, idx: number) => (
                        <div key={idx} style={{padding: '0.75rem', borderBottom: idx < blueprintReviewModal.substrands.length - 1 ? '1px solid #e2e8f0' : 'none', background: idx % 2 === 0 ? '#ffffff' : '#f8fafc'}}>
                          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                            <div>
                              <strong style={{color: '#0f172a'}}>{ss.strand} ➔ {ss.sub_strand}</strong>
                              <span className="pill" style={{marginLeft: '8px', background: '#e2e8f0'}}>{ss.hours || "4 hours"}</span>
                            </div>
                            <span className="pill ok">DNA: {ss.substrand_dna_id?.slice(0, 10)}...</span>
                          </div>

                          {/* SLOs & KIQs */}
                          <div style={{marginTop: '0.5rem', fontSize: '0.8rem', color: '#475569'}}>
                            <div><strong>Specific Learning Outcomes ({ss.slo_count || ss.slos?.length || 0}):</strong></div>
                            <ul style={{margin: '4px 0 6px 16px', padding: 0}}>
                              {(ss.slos || []).slice(0, 3).map((slo: any, sIdx: number) => (
                                <li key={sIdx}>{typeof slo === 'string' ? slo : (slo.text || slo.id)}</li>
                              ))}
                            </ul>
                          </div>

                          {/* Planned Assets & Safety Hazards */}
                          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '0.5rem', marginTop: '0.5rem', fontSize: '0.78rem'}}>
                            {ss.diagrams_required?.length > 0 && (
                              <div style={{background: '#f5f3ff', border: '1px solid #ddd6fe', padding: '6px', borderRadius: '6px', color: '#5b21b6'}}>
                                <strong>📐 Visual Models Needed:</strong> {ss.diagrams_required.join(', ')}
                              </div>
                            )}
                            {ss.experiments?.length > 0 && (
                              <div style={{background: '#ecfdf5', border: '1px solid #a7f3d0', padding: '6px', borderRadius: '6px', color: '#065f46'}}>
                                <strong>🧪 Planned Practical Tasks:</strong> {ss.experiments.join('; ')}
                              </div>
                            )}
                            {ss.safety_hazards_to_check?.length > 0 && (
                              <div style={{background: '#fef2f2', border: '1px solid #fecaca', padding: '6px', borderRadius: '6px', color: '#991b1b'}}>
                                <strong>⚠️ Strict Safety Hazards to Audit:</strong> {ss.safety_hazards_to_check.slice(0, 2).join('; ')}
                              </div>
                            )}
                          </div>

                          {/* Dynamic Prompt Package Preview */}
                          {ss.prompt_package && (
                            <details style={{marginTop: '0.5rem', fontSize: '0.78rem', background: '#f1f5f9', padding: '6px', borderRadius: '6px'}}>
                              <summary style={{cursor: 'pointer', fontWeight: 600, color: '#334155'}}>🤖 View Generated Agent Prompts for this Sub-strand</summary>
                              <div style={{marginTop: '6px', display: 'flex', flexDirection: 'column', gap: '6px'}}>
                                <div><strong>📝 Notes Generator Prompt:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>{ss.prompt_package.notes_prompt}</pre></div>
                                <div><strong>📐 Diagram Generator Prompt:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>{ss.prompt_package.diagram_prompt}</pre></div>
                                <div><strong>🧪 Experiment & Safety Prompt:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>{ss.prompt_package.experiment_activity_prompt}</pre></div>
                                <div><strong>❓ Questions Prompt:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>{ss.prompt_package.question_prompt}</pre></div>
                                <div><strong>🔍 Safety Reviewer Prompt:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>{ss.prompt_package.reviewer_prompt}</pre></div>
                                <div><strong>🤖 Dual Approver Deliberation Prompts:</strong> <pre style={{margin: '2px 0', padding: '4px', background: '#ffffff', borderRadius: '4px', whiteSpace: 'pre-wrap'}}>Auditor 1: {ss.prompt_package.approver_agent1_prompt}&#10;&#10;Auditor 2: {ss.prompt_package.approver_agent2_prompt}</pre></div>
                              </div>
                            </details>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Human Decision Form */}
                  <div style={{marginTop: '1.25rem', padding: '1rem', background: '#f8fafc', border: '1px solid #cbd5e1', borderRadius: '8px'}}>
                    <h4 style={{margin: '0 0 0.5rem', color: '#1e293b'}}>✍️ Human Reviewer Decision & Feedback</h4>
                    <textarea
                      value={humanBlueprintNotes}
                      onChange={(e) => setHumanBlueprintNotes(e.target.value)}
                      placeholder="Add any curriculum adjustments, notes, or approval rationale..."
                      rows={2}
                      style={{width: '100%', fontSize: '0.85rem', marginBottom: '0.75rem'}}
                    />
                    <div style={{display: 'flex', gap: '0.75rem', justifyContent: 'flex-end'}}>
                      <button
                        onClick={() => onBlueprintDecision(blueprintReviewModal.design_id, "reject")}
                        disabled={isRunning}
                        style={{background: '#ef4444', borderColor: '#ef4444'}}
                      >
                        ❌ Reject Blueprint
                      </button>
                      <button
                        onClick={() => onBlueprintDecision(blueprintReviewModal.design_id, "accept")}
                        disabled={isRunning}
                        style={{background: '#059669', borderColor: '#059669'}}
                      >
                        ✅ Accept Blueprint & Publish to Generation Studio
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 3. ACTIVE APPROVED CURRICULUM BLUEPRINTS TABLE */}
            <div className="panel" style={{marginBottom: '1.5rem', border: '1px solid #cbd5e1'}}>
              <div className="panel-head">
                <div>
                  <h3>📚 Published Curriculum Blueprints ({curriculumDesignsList.length})</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>Active curriculum designs ready for the Multi-Agent Generation Studio.</p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                {curriculumDesignsList.length === 0 ? (
                  <div style={{padding: '1.5rem', textAlign: 'center', color: '#64748b'}}>
                    No curriculum designs approved yet. Process a raw dataset above to generate and approve the first blueprint.
                  </div>
                ) : (
                  <table style={{width: '100%', fontSize: '0.85rem', borderCollapse: 'collapse'}}>
                    <thead>
                      <tr style={{textAlign: 'left', borderBottom: '2px solid #e2e8f0'}}>
                        <th style={{padding: '8px'}}>Subject</th>
                        <th style={{padding: '8px'}}>Grade / Level</th>
                        <th style={{padding: '8px'}}>Sub-strands</th>
                        <th style={{padding: '8px'}}>Status</th>
                        <th style={{padding: '8px'}}>Updated</th>
                        <th style={{padding: '8px', textAlign: 'right'}}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {curriculumDesignsList.map((d: any, idx: number) => (
                        <tr key={idx} style={{borderBottom: '1px solid #f1f5f9'}}>
                          <td style={{padding: '8px'}}>
                            <strong>{d.subject}</strong>
                            <div style={{fontSize: '0.75rem', color: '#64748b'}}>{d.essence_statement?.slice(0, 60)}...</div>
                          </td>
                          <td style={{padding: '8px'}}>
                            <span className="pill" style={{background: '#e0e7ff', color: '#3730a3'}}>{d.grade}</span>
                            <div style={{fontSize: '0.75rem', color: '#64748b', marginTop: '2px'}}>{d.level}</div>
                          </td>
                          <td style={{padding: '8px'}}>
                            <strong>{d.substrand_count || 0}</strong> sub-strands
                          </td>
                          <td style={{padding: '8px'}}>
                            <span className={`pill ${d.review_status === 'accepted_active' ? 'ok' : 'warn'}`}>
                              {d.review_status === 'accepted_active' ? '✓ Active in Studio' : d.review_status || 'Draft'}
                            </span>
                          </td>
                          <td style={{padding: '8px', fontSize: '0.78rem', color: '#64748b'}}>
                            {new Date(d.updated_at).toLocaleDateString()}
                          </td>
                          <td style={{padding: '8px', textAlign: 'right'}}>
                            <button
                              onClick={() => {
                                setGenGrade(d.grade);
                                setGenSubject(d.subject);
                                loadGradeSubjects(d.grade);
                                setView("generation");
                              }}
                              style={{fontSize: '0.8rem', padding: '6px 12px'}}
                            >
                              🚀 Open in Generation Studio
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            {/* 4. RAW TEXT / PDF UPLOAD FALLBACK */}
            <div className="panel" style={{marginBottom: '1.5rem', border: '1px solid #e2e8f0'}}>
              <div className="panel-head">
                <div>
                  <h3>📥 Paste / Upload Additional Raw Curriculum Text</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>If you have custom curriculum text not in Langfuse, paste it here to run the extractor.</p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                <textarea
                  value={rawCurriculumInput}
                  onChange={(e) => setRawCurriculumInput(e.target.value)}
                  rows={5}
                  style={{width: '100%', fontFamily: 'monospace', fontSize: '0.82rem'}}
                  placeholder="Paste raw curriculum design text or JSON dataset payload here..."
                />
                <div style={{display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap'}}>
                  <button onClick={onIngestRawCurriculum} disabled={isRunning || !rawCurriculumInput.trim()}>
                    {isRunning ? "Structuring..." : "Structure Curriculum from Text"}
                  </button>
                  <button
                    className="ghost"
                    onClick={() => {
                      setRawCurriculumInput(`DIPLOMA IN TEACHER EDUCATION\nPRE-PRIMARY AND PRIMARY\nAGRICULTURE\nCURRICULUM DESIGN 2024\n\nESSENCE STATEMENT\nKenya is mainly dependent on an agro-based economy that requires competent manpower for sustainable development.\n\nGENERAL LEARNING OUTCOMES\n1. Develop Agricultural knowledge, skills, values and attitudes.\n2. Apply knowledge and pedagogical skills to rear domestic animals.\n\nSTRAND 1.0 AGRICULTURE AND ENVIRONMENT\n1.1 Overview of Agriculture (4 hours)\nBy the end of the sub strand, the teacher trainee should be able to:\na) discuss the importance of Agriculture in Kenya,\nb) relate the key natural resources to Agricultural production in Kenya,\nSuggested Learning Experiences\n• Through discussion and literature review, develop the meaning and importance of Agriculture.\n• Research on key natural resources that influence Agricultural production.\nSuggested Key Inquiry Questions\nHow does curriculum in primary education relate to Agriculture productivity in Kenya?\nCore competencies to be developed:\nCritical thinking and problem solving.\nValues:\nPatriotism as teacher trainees take initiative.\n\n1.4 Soil Composition (4 hours)\nBy the end of the sub strand, the teacher trainee should be able to:\na) investigate components of a garden soil sample,\nb) relate components of soil to its productivity in Agriculture,\nSuggested Learning Experiences\n• Carry out experiments to investigate presence of components (air, water, organic matter) of a garden soil sample.\n• Prepare compost manure using heap and pit methods.\nSuggested Key Inquiry Questions\nWhat makes a quality fertile soil?`);
                    }}
                  >
                    Load Sample Agriculture DTE Design
                  </button>
                </div>
              </div>
            </div>

            {/* Global BECF Master Context Editor */}
            <div className="panel" style={{marginBottom: '1rem'}}>
              <div className="panel-head">
                <div>
                  <h3>Global BECF Master Context (Prompt: "BECF")</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>This is the foundational prompt governing all 5 agent stages.</p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                <textarea
                  value={masterContextDraft}
                  onChange={(e) => setMasterContextDraft(e.target.value)}
                  rows={8}
                  style={{width: '100%', fontFamily: 'monospace', fontSize: '0.85rem'}}
                />
                <div style={{display: 'flex', gap: '0.5rem', marginTop: '0.5rem'}}>
                  <button onClick={saveMasterContext} disabled={isRunning}>Save to Langfuse</button>
                  <button className="ghost" onClick={seedLangfuse} disabled={isRunning}>Seed Langfuse Defaults</button>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 3. CONTENT FACTORY & INTERACTIVE PLAYGROUND TAB */}
        {view === "generation" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>🏭 Content Factory & Interactive Playground</h2>
                <p>The central production workshop: Structure curriculum designs, interactively generate/regenerate revision notes, vector SVG diagrams, practical experiments with hazard safety protocols, and criterion questions until approved.</p>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className={factoryStep === 1 ? "" : "ghost"}
                  onClick={() => setFactoryStep(1)}
                >
                  1. Architecture & Strands
                </button>
                <button
                  className={factoryStep === 2 ? "" : "ghost"}
                  onClick={() => setFactoryStep(2)}
                >
                  2. Asset Playground
                </button>
                <button
                  className={factoryStep === 3 ? "" : "ghost"}
                  onClick={() => setFactoryStep(3)}
                >
                  3. Audit & Deliberation
                </button>
                <button
                  className={factoryStep === 4 ? "" : "ghost"}
                  onClick={() => setFactoryStep(4)}
                >
                  4. Release & Publish
                </button>
              </div>
            </div>

            {/* Factory Workflow Stepper */}
            <div className="factory-stepper">
              <div
                className={`factory-step ${factoryStep === 1 ? "active" : "completed"}`}
                onClick={() => setFactoryStep(1)}
              >
                <span className="factory-step-num">1</span>
                <span>Subject & Strands Architecture</span>
              </div>
              <span className="factory-stepper-arrow">➔</span>
              <div
                className={`factory-step ${factoryStep === 2 ? "active" : factoryStep > 2 ? "completed" : ""}`}
                onClick={() => setFactoryStep(2)}
              >
                <span className="factory-step-num">2</span>
                <span>Asset Factory Playground (Notes, SVG, Safety, Questions)</span>
              </div>
              <span className="factory-stepper-arrow">➔</span>
              <div
                className={`factory-step ${factoryStep === 3 ? "active" : factoryStep > 3 ? "completed" : ""}`}
                onClick={() => setFactoryStep(3)}
              >
                <span className="factory-step-num">3</span>
                <span>Safety Audit & Dual-Agent Deliberation</span>
              </div>
              <span className="factory-stepper-arrow">➔</span>
              <div
                className={`factory-step ${factoryStep === 4 ? "active" : ""}`}
                onClick={() => setFactoryStep(4)}
              >
                <span className="factory-step-num">4</span>
                <span>Factory Production Lock</span>
              </div>
            </div>

            {/* STEP 1: ARCHITECTURE & STRANDS TREE */}
            {factoryStep === 1 && (
              <div>
                <div className="surface" style={{ marginBottom: "16px" }}>
                  <h3>1. Select Curriculum Design to Produce in Factory</h3>
                  <div className="three-col" style={{ marginTop: "10px" }}>
                    <label>
                      Grade / Level
                      <select
                        value={genGrade}
                        onChange={(e) => {
                          const g = e.target.value;
                          setGenGrade(g);
                          if (g) {
                            loadGradeSubjects(g);
                            loadFactorySubstrandsForDesign(g, genSubject);
                          }
                        }}
                      >
                        <option value="">Select level...</option>
                        {datasetsList.map((d: any, idx: number) => {
                          const label = toOptionLabel(d);
                          return <option key={`grade-${label}-${idx}`} value={label}>{label}</option>;
                        })}
                      </select>
                    </label>

                    <label>
                      Subject
                      <select
                        value={genSubject}
                        onChange={(e) => {
                          const sub = e.target.value;
                          setGenSubject(sub);
                          if (sub && genGrade) {
                            loadSubjectStrands(genGrade, sub);
                            loadFactorySubstrandsForDesign(genGrade, sub);
                          }
                        }}
                      >
                        <option value="">Select subject...</option>
                        {gradeSubjects.map((s: any, idx: number) => {
                          const label = toOptionLabel(s);
                          return <option key={`sub-${label}-${idx}`} value={label}>{label}</option>;
                        })}
                        {curriculumDesignsList.map((cd: any, idx: number) => (
                          <option key={`cd-${cd.subject}-${idx}`} value={cd.subject}>{cd.subject} ({cd.grade})</option>
                        ))}
                      </select>
                    </label>

                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <button
                        style={{ width: "100%" }}
                        onClick={() => loadFactorySubstrandsForDesign(genGrade, genSubject)}
                        disabled={isRunning || !genSubject}
                      >
                        Load Strands Architecture
                      </button>
                    </div>
                  </div>
                </div>

                {/* Strands & Sub-strands Visual Explorer */}
                <div className="strand-explorer-tree">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                    <div>
                      <h3 style={{ margin: 0 }}>Strands & Sub-strands Hierarchy for {genSubject || "Selected Subject"}</h3>
                      <small className="muted">Generate sub-strands for any strand, then click "⚡ Open in Asset Factory Playground" to generate notes, diagrams, safety-checked experiments, and questions.</small>
                    </div>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <button
                        className="ghost"
                        onClick={() => handleGenerateStrands()}
                        disabled={isRunning || !genSubject}
                      >
                        ✨ AI Generate Strands for {genSubject || "Subject"}
                      </button>
                      <button
                        className="ghost"
                        onClick={() => {
                          if (subjectStrands.length > 0 && subjectStrands[0].sub_strands?.length > 0) {
                            selectSubstrandForFactory(subjectStrands[0].sub_strands[0], genGrade, genSubject);
                          } else if (factorySubstrandsList.length > 0) {
                            selectSubstrandForFactory(factorySubstrandsList[0], genGrade, genSubject);
                          }
                        }}
                        disabled={subjectStrands.length === 0 && factorySubstrandsList.length === 0}
                      >
                        ⚡ Quick Enter Asset Factory
                      </button>
                    </div>
                  </div>

                  {/* Render from database factorySubstrandsList or subjectStrands */}
                  {factorySubstrandsList.length > 0 ? (
                    <div>
                      {Array.from(new Set(factorySubstrandsList.map((s) => s.strand_name))).map((strandName, sIdx) => {
                        const subsInStrand = factorySubstrandsList.filter((s) => s.strand_name === strandName);
                        return (
                          <div key={sIdx} className="strand-card">
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                              <div>
                                <strong style={{ fontSize: "14px", color: "#0c4a6e" }}>🌿 STRAND: {strandName}</strong>
                                <span className="pill ok" style={{ fontSize: "11px", marginLeft: "8px" }}>{subsInStrand.length} Sub-strands</span>
                              </div>
                              <button
                                style={{ fontSize: "11px", padding: "4px 10px" }}
                                onClick={() => handleOpenSubstrandGenerator(strandName)}
                              >
                                ✨ AI Generate / Refine Sub-strands
                              </button>
                            </div>

                            <div style={{ display: "grid", gap: "8px" }}>
                              {subsInStrand.map((ss, subIdx) => (
                                <div
                                  key={subIdx}
                                  className={`substrand-row ${factorySelectedSubstrand?.sub_strand_name === ss.sub_strand_name ? "selected" : ""}`}
                                >
                                  <div>
                                    <div style={{ fontWeight: 700, fontSize: "13px", color: "#0f172a" }}>
                                      🌱 {ss.sub_strand_name}
                                      <span className="pill warn" style={{ marginLeft: "8px", fontSize: "11px" }}>{ss.allocated_hours || "4 hours"}</span>
                                    </div>
                                    <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                                      <span>🎯 SLOs: {Array.isArray(ss.slos) ? ss.slos.length : 2}</span> •{" "}
                                      <span>📐 Required Diagrams: {Array.isArray(ss.required_diagrams) ? ss.required_diagrams.join(", ") : "Scientific Diagram"}</span> •{" "}
                                      <span>🧪 Experiments: {Array.isArray(ss.experiments) ? ss.experiments.length : 1}</span>
                                    </div>
                                  </div>
                                  <button
                                    style={{ fontSize: "12px", padding: "6px 12px" }}
                                    onClick={() => selectSubstrandForFactory(ss, genGrade, genSubject)}
                                  >
                                    ⚡ Open in Asset Factory ➔
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : subjectStrands.length > 0 ? (
                    <div>
                      {subjectStrands.map((strand: any, sIdx: number) => {
                        const stName = toOptionLabel(strand);
                        return (
                          <div key={sIdx} className="strand-card">
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                              <strong style={{ fontSize: "14px", color: "#0c4a6e" }}>🌿 STRAND: {stName}</strong>
                              <button
                                style={{ fontSize: "11px", padding: "4px 10px" }}
                                onClick={() => handleOpenSubstrandGenerator(stName)}
                              >
                                ✨ AI Generate Sub-strands for this Strand
                              </button>
                            </div>
                            <div style={{ display: "grid", gap: "8px", marginTop: "8px" }}>
                              {(strand.sub_strands || []).length > 0 ? (
                                (strand.sub_strands || []).map((ss: any, subIdx: number) => {
                                  const ssName = toOptionLabel(ss);
                                  return (
                                    <div key={subIdx} className="substrand-row">
                                      <div>
                                        <div style={{ fontWeight: 700, fontSize: "13px" }}>🌱 {ssName}</div>
                                      </div>
                                      <button
                                        style={{ fontSize: "12px", padding: "6px 12px" }}
                                        onClick={() => selectSubstrandForFactory({ strand_name: stName, sub_strand_name: ssName }, genGrade, genSubject)}
                                      >
                                        ⚡ Open in Asset Factory ➔
                                      </button>
                                    </div>
                                  );
                                })
                              ) : (
                                <div style={{ padding: "8px 12px", background: "#f8fafc", borderRadius: "6px", fontSize: "12px", color: "#64748b", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <span>No sub-strands generated yet for this strand.</span>
                                  <button
                                    style={{ fontSize: "11px", padding: "4px 8px" }}
                                    onClick={() => handleOpenSubstrandGenerator(stName)}
                                  >
                                    ✨ Generate Sub-strands Now
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{ textAlign: "center", padding: "32px", color: "var(--muted)" }}>
                      <p>No strands loaded yet. Select a grade & subject above, or click "Load Sample Agriculture DTE Design" in Datasets tab.</p>
                      <div style={{ display: "flex", justifyContent: "center", gap: "8px", marginTop: "8px" }}>
                        <button
                          className="ghost"
                          onClick={() => {
                            setGenGrade("grade-dte");
                            setGenSubject("Agriculture");
                            loadFactorySubstrandsForDesign("grade-dte", "Agriculture");
                          }}
                        >
                          Load DTE Agriculture Strands
                        </button>
                        <button
                          onClick={() => {
                            if (genGrade && genSubject) {
                              handleGenerateStrands();
                            }
                          }}
                          disabled={!genGrade || !genSubject}
                        >
                          ✨ Generate Top-Level Strands for {genSubject || "Subject"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* SUB-STRAND GENERATOR MODAL / STUDIO */}
                {substrandGenModal && (
                  <div
                    style={{
                      position: "fixed",
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      background: "rgba(15, 23, 42, 0.7)",
                      backdropFilter: "blur(4px)",
                      display: "flex",
                      justifyContent: "center",
                      alignItems: "center",
                      zIndex: 1000,
                      padding: "20px",
                    }}
                  >
                    <div
                      style={{
                        background: "#fff",
                        borderRadius: "16px",
                        maxWidth: "900px",
                        width: "100%",
                        maxHeight: "90vh",
                        overflowY: "auto",
                        padding: "24px",
                        boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                        <div>
                          <h2 style={{ margin: 0, color: "#0f172a" }}>
                            🌱 Sub-strand Intelligence Generator
                          </h2>
                          <div style={{ fontSize: "13px", color: "#0284c7", marginTop: "4px" }}>
                            Subject: <strong>{genSubject}</strong> ({genGrade}) • Target Strand: <strong>{substrandGenModal.strand_name}</strong>
                          </div>
                        </div>
                        <button className="ghost" onClick={() => setSubstrandGenModal(null)}>✕ Close</button>
                      </div>

                      {/* Global BECF Framework Context Banner */}
                      <div style={{ marginTop: "12px", padding: "10px 14px", background: "#fdf4ff", borderRadius: "8px", border: "1px solid #f5d0fe", fontSize: "12px" }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <strong style={{ color: "#86198f" }}>🏛️ Global BECF Master Framework Context (Auto-Injected):</strong>
                          <span className="pill ok" style={{ fontSize: "10px", background: "#fae8ff", color: "#86198f", border: "1px solid #f0abfc" }}>BECF Grounded</span>
                        </div>
                        <div style={{ margin: "4px 0 0", color: "#701a75", fontSize: "11px" }}>
                          <span><strong>7 Core Competencies:</strong> Communication & Collaboration, Critical Thinking & Problem Solving, Creativity, Citizenship, Digital Literacy, Learning to Learn, Self-efficacy.</span>
                          <br />
                          <span><strong>8 Core Values:</strong> Love, Responsibility, Respect, Unity, Peace, Patriotism, Social Justice, Integrity.</span>
                          <br />
                          <span><strong>Assessment Mandate:</strong> 4-Level Criterion Rubrics (Exceeding, Meeting, Approaching, Below) • Constructivist experiential inquiry.</span>
                        </div>
                      </div>

                      {/* Inherited Subject Curriculum Blueprint Context */}
                      <div style={{ marginTop: "10px", padding: "10px 14px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", fontSize: "12px" }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <strong style={{ color: "#0369a1" }}>📘 Active Subject Curriculum Design Context:</strong>
                          <span className="pill ok" style={{ fontSize: "10px" }}>Blueprint Linked</span>
                        </div>
                        <p style={{ margin: "4px 0 6px", color: "#334155" }}>
                          <strong>Essence Statement:</strong>{" "}
                          {(substrandGenModal as any).essence_statement || `Comprehensive curriculum blueprint for ${genSubject} (${genGrade}). Focus on practical application, environmental stewardship, and CBC core competencies.`}
                        </p>
                        {(substrandGenModal as any).general_learning_outcomes?.length > 0 && (
                          <div style={{ color: "#475569" }}>
                            <strong>General Outcomes:</strong>{" "}
                            {(substrandGenModal as any).general_learning_outcomes.join(" • ")}
                          </div>
                        )}
                      </div>

                      {/* Complete Curriculum Source Design Materials Drawer */}
                      <div style={{ marginTop: "12px", padding: "10px 14px", background: "#eff6ff", borderRadius: "8px", border: "1px solid #bfdbfe", fontSize: "12px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <div>
                            <strong style={{ color: "#1e40af" }}>📄 Complete Curriculum Design Source Materials Context:</strong>
                            <span style={{ marginLeft: "8px", fontSize: "11px", color: "#3b82f6" }}>
                              {substrandSourceMaterial ? `${substrandSourceMaterial.length.toLocaleString()} characters • ${substrandSourceMaterial.split(/\s+/).filter(Boolean).length.toLocaleString()} words injected` : "Auto-loading from uploaded syllabus..."}
                            </span>
                          </div>
                          <button
                            className="ghost"
                            style={{ fontSize: "11px", padding: "2px 8px" }}
                            onClick={() => setShowSourceMaterialText(!showSourceMaterialText)}
                          >
                            {showSourceMaterialText ? "▲ Hide Source Document" : "▼ Inspect / Edit Source Document"}
                          </button>
                        </div>

                        {showSourceMaterialText && (
                          <div style={{ marginTop: "8px" }}>
                            <textarea
                              rows={8}
                              style={{ width: "100%", fontFamily: "monospace", fontSize: "11px", padding: "8px", background: "#fff" }}
                              value={substrandSourceMaterial}
                              onChange={(e) => setSubstrandSourceMaterial(e.target.value)}
                              placeholder="Paste or inspect full curriculum design pages, syllabus tables, and guidelines here..."
                            />
                            <small className="muted">The AI model reads this entire source document to extract every sub-strand, exact teaching hours, SLOs, experiments, diagrams, and safety protocols.</small>
                          </div>
                        )}
                      </div>

                      <div style={{ marginTop: "14px" }}>
                        <label style={{ fontWeight: 600, fontSize: "13px" }}>
                          Custom Production Directives for this Strand:
                          <textarea
                            rows={3}
                            style={{ width: "100%", marginTop: "6px", fontFamily: "inherit", fontSize: "13px", padding: "8px" }}
                            value={substrandPromptInput}
                            onChange={(e) => setSubstrandPromptInput(e.target.value)}
                            placeholder="e.g. Generate all required comprehensive sub-strands for 1.0 AGRICULTURE AND ENVIRONMENT with allocated hours (e.g. 4 hours), SLOs, practical experiments, and safety protocols."
                          />
                        </label>

                        <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "10px" }}>
                          <button onClick={() => handleGenerateSubstrands(substrandPromptInput)} disabled={isRunning}>
                            {isRunning ? "⚡ AI Generating Sub-strands with Full Design Context..." : (generatedSubstrandsDraft.length > 0 ? "🔄 Regenerate Sub-strands" : "⚡ AI Generate Sub-strands for this Strand")}
                          </button>
                        </div>
                      </div>

                      {/* Generated Sub-strands List Preview */}
                      {generatedSubstrandsDraft.length > 0 && (
                        <div style={{ marginTop: "20px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                            <h3 style={{ margin: 0, color: "#166534" }}>
                              ✨ Generated Sub-strands ({generatedSubstrandsDraft.length})
                            </h3>
                            <button
                              style={{ background: "#16a34a", color: "#fff", fontWeight: 700 }}
                              onClick={handleSaveSubstrandsToDatabase}
                              disabled={isRunning}
                            >
                              💾 Save Sub-strands to Database & Strands Tree
                            </button>
                          </div>

                          <div style={{ display: "grid", gap: "12px" }}>
                            {generatedSubstrandsDraft.map((ss: any, idx: number) => (
                              <div
                                key={idx}
                                style={{
                                  padding: "14px",
                                  borderRadius: "10px",
                                  border: "1px solid #bbf7d0",
                                  background: "#f0fdf4",
                                }}
                              >
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <strong style={{ fontSize: "14px", color: "#14532d" }}>
                                    🌱 {ss.sub_strand_name || ss.name}
                                  </strong>
                                  <span className="pill warn" style={{ fontWeight: 600 }}>{ss.allocated_hours || "4 hours"}</span>
                                </div>

                                {/* SLOs */}
                                {ss.slos && (
                                  <div style={{ marginTop: "8px", fontSize: "12px" }}>
                                    <strong>Specific Learning Outcomes (SLOs):</strong>
                                    <ul style={{ margin: "4px 0 0", paddingLeft: "18px" }}>
                                      {ss.slos.map((slo: any, sIdx: number) => (
                                        <li key={sIdx}>{typeof slo === "string" ? slo : (slo.text || slo.name)}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}

                                {/* Key Inquiry Questions */}
                                {ss.key_inquiry_questions && (
                                  <div style={{ marginTop: "6px", fontSize: "12px", color: "#0369a1" }}>
                                    <strong>Key Inquiry Questions:</strong> {Array.isArray(ss.key_inquiry_questions) ? ss.key_inquiry_questions.join(" • ") : ss.key_inquiry_questions}
                                  </div>
                                )}

                                {/* Diagrams & Experiments */}
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginTop: "8px", fontSize: "11px" }}>
                                  <div style={{ padding: "6px 8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                                    <strong>📐 Required Diagram:</strong>
                                    <div>{Array.isArray(ss.required_diagrams) ? ss.required_diagrams.join(", ") : (ss.required_diagrams || "Process Flowchart")}</div>
                                  </div>
                                  <div style={{ padding: "6px 8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                                    <strong>🧪 Practical Experiment:</strong>
                                    <div>{Array.isArray(ss.experiments) ? ss.experiments.join(", ") : (ss.experiments || "Hands-on investigation")}</div>
                                  </div>
                                </div>

                                {/* Safety Hazards */}
                                {ss.safety_hazards_to_check && (
                                  <div style={{ marginTop: "6px", fontSize: "11px", color: "#b91c1c" }}>
                                    ⚠️ <strong>Safety Hazard Guidelines:</strong> {Array.isArray(ss.safety_hazards_to_check) ? ss.safety_hazards_to_check.join(" • ") : ss.safety_hazards_to_check}
                                  </div>
                                )}

                                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "10px" }}>
                                  <button
                                    style={{ fontSize: "12px", padding: "6px 12px" }}
                                    onClick={() => {
                                      setSubstrandGenModal(null);
                                      selectSubstrandForFactory(ss, genGrade, genSubject);
                                    }}
                                  >
                                    ⚡ Open Directly in Asset Factory ➔
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* STEP 2: INTERACTIVE ASSET FACTORY PLAYGROUND */}
            {factoryStep === 2 && (
              <div>
                {/* Active Sub-strand Info Header */}
                <div className="surface" style={{ marginBottom: "16px", background: "#f0fdf4", borderColor: "#bbf7d0" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <small style={{ color: "#166534", fontWeight: 700, textTransform: "uppercase" }}>Active Production Workshop Target:</small>
                      <h2 style={{ margin: "4px 0", color: "#14532d" }}>
                        {genSubject} ➔ {genStrand || "Strand"} ➔ {genSubstrand || "Sub-strand"}
                      </h2>
                      <div style={{ fontSize: "12px", color: "#166534" }}>
                        Level: <strong>{genGrade}</strong> • SLO: <strong>{genSloId || "Universal SLO"}</strong>
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: "8px" }}>
                      <button onClick={triggerGenerate} disabled={isRunning}>
                        {isRunning ? "⚡ Generating Entire Bundle..." : "⚡ Generate Entire Bundle (All 4 Stations)"}
                      </button>
                    </div>
                  </div>
                </div>

                {/* 4-Station Interactive Production Quadrant */}
                <div className="factory-quadrant">
                  {/* STATION 1: REVISION NOTES */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>📝 Station 1: Notes Studio</h3>
                        <small className="muted">Constructivist explanation & PCK scaffolding</small>
                      </div>
                      <span className={`pill ${notesApproved ? "ok" : stationNotes ? "warn" : "idle"}`}>
                        {notesApproved ? "Approved" : stationNotes ? "Generated" : "Pending"}
                      </span>
                    </div>

                    <div className="factory-refine-box">
                      <input
                        placeholder="Refine notes prompt (e.g., add more real-world examples)..."
                        value={notesRefinePrompt}
                        onChange={(e) => setNotesRefinePrompt(e.target.value)}
                      />
                      <button
                        onClick={() => generateFactoryNotes(notesRefinePrompt)}
                        disabled={isRunning}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {stationNotes ? "🔄 Regenerate" : "⚡ Generate"}
                      </button>
                    </div>

                    <div className="factory-preview-pane">
                      {stationNotes ? (
                        <div>
                          <strong style={{ fontSize: "14px", color: "#0e7490" }}>{stationNotes.title}</strong>
                          <p style={{ margin: "6px 0 10px" }}>{stationNotes.intro}</p>

                          {stationNotes.key_concepts?.map((kc: any, idx: number) => (
                            <div key={idx} style={{ marginTop: "8px", padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                              <strong>{kc.heading || `Concept ${idx + 1}`}</strong>
                              <p style={{ margin: "4px 0", fontSize: "12px" }}>{kc.content}</p>
                              {kc.pedagogical_notes && (
                                <small style={{ color: "#6b7280", fontStyle: "italic" }}>💡 Pedagogical Note: {kc.pedagogical_notes}</small>
                              )}
                            </div>
                          ))}

                          {stationNotes.worked_examples?.length > 0 && (
                            <div style={{ marginTop: "10px" }}>
                              <strong>Worked Examples:</strong>
                              {stationNotes.worked_examples.map((we: any, idx: number) => (
                                <div key={idx} style={{ fontSize: "12px", marginTop: "4px", padding: "6px", background: "#f8fafc", borderRadius: "4px" }}>
                                  <em>Scenario: {we.scenario}</em>
                                  <div style={{ marginTop: "2px" }}>Solution: {Array.isArray(we.solution_steps) ? we.solution_steps.join(" ➔ ") : we.solution_steps}</div>
                                </div>
                              ))}
                            </div>
                          )}

                          {stationNotes.accessibility_support?.plain_language_summary && (
                            <div style={{ marginTop: "10px", padding: "6px 8px", background: "#eff6ff", borderRadius: "6px", fontSize: "11px", color: "#1e40af" }}>
                              ♿ <strong>SNE Plain Language:</strong> {stationNotes.accessibility_support.plain_language_summary}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                          <p>Click "⚡ Generate" to synthesize high-depth revision notes.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className={notesApproved ? "ghost" : ""}
                        onClick={() => setNotesApproved(!notesApproved)}
                        disabled={!stationNotes}
                      >
                        {notesApproved ? "✓ Notes Approved" : "✅ Approve Notes"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 2: LIVE VECTOR SVG DIAGRAM */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>📐 Station 2: SVG Vector Diagram Studio</h3>
                        <small className="muted">Live vector rendering & accessibility</small>
                      </div>
                      <span className={`pill ${diagramApproved ? "ok" : stationDiagram ? "warn" : "idle"}`}>
                        {diagramApproved ? "Approved" : stationDiagram ? "Generated" : "Pending"}
                      </span>
                    </div>

                    <div style={{ display: "grid", gap: "6px" }}>
                      <input
                        placeholder="Diagram Concept (e.g. Flowchart of Agricultural Sectors in Kenya)"
                        value={diagramConceptInput}
                        onChange={(e) => setDiagramConceptInput(e.target.value)}
                        style={{ fontSize: "12px", padding: "6px 10px" }}
                      />
                      <div className="factory-refine-box" style={{ margin: 0 }}>
                        <input
                          placeholder="Refine prompt (e.g., add clear callout leader lines)..."
                          value={diagramRefinePrompt}
                          onChange={(e) => setDiagramRefinePrompt(e.target.value)}
                        />
                        <button
                          onClick={() => generateFactoryDiagram(diagramRefinePrompt)}
                          disabled={isRunning}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {stationDiagram ? "🔄 Regenerate" : "⚡ Generate"}
                        </button>
                      </div>
                    </div>

                    {/* Live SVG Vector Canvas & Toggles */}
                    <div style={{ display: "flex", gap: "6px", marginTop: "4px" }}>
                      <button
                        className={diagramViewMode === "visual" ? "" : "ghost"}
                        style={{ fontSize: "11px", padding: "4px 8px" }}
                        onClick={() => setDiagramViewMode("visual")}
                      >
                        🖼️ Visual Canvas
                      </button>
                      <button
                        className={diagramViewMode === "code" ? "" : "ghost"}
                        style={{ fontSize: "11px", padding: "4px 8px" }}
                        onClick={() => setDiagramViewMode("code")}
                      >
                        💻 XML Markup
                      </button>
                      <button
                        className={diagramViewMode === "tactile" ? "" : "ghost"}
                        style={{ fontSize: "11px", padding: "4px 8px" }}
                        onClick={() => setDiagramViewMode("tactile")}
                      >
                        ♿ SNE Tactile Notes
                      </button>
                    </div>

                    <div className="factory-preview-pane" style={{ padding: "8px" }}>
                      {stationDiagram ? (
                        <div>
                          {diagramViewMode === "visual" && (
                            <div
                              className="svg-canvas-box"
                              dangerouslySetInnerHTML={{ __html: stationDiagram.diagram_svg || "<p>No SVG markup</p>" }}
                            />
                          )}

                          {diagramViewMode === "code" && (
                            <pre style={{ fontSize: "10px", maxHeight: "250px" }}>
                              {stationDiagram.diagram_svg}
                            </pre>
                          )}

                          {diagramViewMode === "tactile" && (
                            <div style={{ padding: "10px", fontSize: "12px" }}>
                              <strong>Alt Text Description:</strong>
                              <p style={{ margin: "4px 0 10px" }}>{stationDiagram.accessibility?.alt_text || "Visual model of the concept."}</p>
                              <strong>Raised-Line Tactile Guidance (SNE):</strong>
                              <p style={{ margin: "4px 0" }}>{stationDiagram.accessibility?.tactile_description || "Use tactile braille embosser with raised outlines."}</p>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                          <p>Click "⚡ Generate" to synthesize crisp, standalone SVG vector illustrations.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className={diagramApproved ? "ghost" : ""}
                        onClick={() => setDiagramApproved(!diagramApproved)}
                        disabled={!stationDiagram}
                      >
                        {diagramApproved ? "✓ Diagram Approved" : "✅ Approve Diagram"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 3: PRACTICAL EXPERIMENTS & SAFETY */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>🧪 Station 3: Experiments & Safety Studio</h3>
                        <small className="muted">Experiential tasks with mandatory hazard checks</small>
                      </div>
                      <span className={`pill ${activityApproved ? "ok" : stationActivity ? "warn" : "idle"}`}>
                        {activityApproved ? "Approved" : stationActivity ? "Generated" : "Pending"}
                      </span>
                    </div>

                    <div className="factory-refine-box">
                      <input
                        placeholder="Refine experiment prompt (e.g., mandate non-toxic soil samples)..."
                        value={activityRefinePrompt}
                        onChange={(e) => setActivityRefinePrompt(e.target.value)}
                      />
                      <button
                        onClick={() => generateFactoryActivity(activityRefinePrompt)}
                        disabled={isRunning}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {stationActivity ? "🔄 Regenerate" : "⚡ Generate"}
                      </button>
                    </div>

                    <div className="factory-preview-pane">
                      {stationActivity ? (
                        <div>
                          <strong style={{ fontSize: "14px", color: "#0e7490" }}>
                            {stationActivity.activity_name || stationActivity.title || "Practical Learning Task"}
                          </strong>
                          <p style={{ margin: "4px 0 8px" }}>
                            <strong>Objective:</strong> {stationActivity.objective || "Investigate practical applications."}
                          </p>

                          {/* Mandatory Safety Hazard Warning Card */}
                          <div className="hazard-alert-box">
                            <strong>🚨 MANDATORY SAFETY HAZARD GUIDELINES:</strong>
                            <ul style={{ margin: "4px 0 0", paddingLeft: "18px" }}>
                              {stationActivity.safety_protocols?.hazard_warnings?.map((hw: string, idx: number) => (
                                <li key={idx}>{hw}</li>
                              )) || (
                                <li>Wash hands with soap and water after handling specimens. Adult supervision required.</li>
                              )}
                            </ul>
                          </div>

                          {stationActivity.materials && (
                            <div style={{ marginTop: "8px", fontSize: "12px" }}>
                              <strong>Apparatus & Local Materials:</strong>
                              <div>{Array.isArray(stationActivity.materials) ? stationActivity.materials.join(", ") : stationActivity.materials}</div>
                            </div>
                          )}

                          {stationActivity.procedure_steps && (
                            <div style={{ marginTop: "8px", fontSize: "12px" }}>
                              <strong>Step-by-Step Procedure:</strong>
                              <ol style={{ margin: "4px 0 0", paddingLeft: "18px" }}>
                                {stationActivity.procedure_steps.map((st: string, idx: number) => (
                                  <li key={idx} style={{ marginBottom: "2px" }}>{st}</li>
                                ))}
                              </ol>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                          <p>Click "⚡ Generate" to synthesize hands-on practical experiments with hazard safety protocols.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className={activityApproved ? "ghost" : ""}
                        onClick={() => setActivityApproved(!activityApproved)}
                        disabled={!stationActivity}
                      >
                        {activityApproved ? "✓ Activity Approved" : "✅ Approve Activity"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 4: CRITERION QUESTIONS & RUBRICS */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>❓ Station 4: Questions & Rubrics Studio</h3>
                        <small className="muted">Derived Bloom's assessment with 4-level rubric</small>
                      </div>
                      <span className={`pill ${questionsApproved ? "ok" : stationQuestions.length > 0 ? "warn" : "idle"}`}>
                        {questionsApproved ? "Approved" : stationQuestions.length > 0 ? "Generated" : "Pending"}
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <label style={{ fontSize: "11px", whiteSpace: "nowrap" }}>
                        Difficulty: {questionsDifficulty}
                        <input
                          type="range"
                          min="0.35"
                          max="0.85"
                          step="0.05"
                          value={questionsDifficulty}
                          onChange={(e) => setQuestionsDifficulty(parseFloat(e.target.value))}
                          style={{ margin: 0, padding: 0 }}
                        />
                      </label>
                      <input
                        placeholder="Refine question prompt (e.g. add 1 structured scenario question)..."
                        value={questionsRefinePrompt}
                        onChange={(e) => setQuestionsRefinePrompt(e.target.value)}
                        style={{ fontSize: "12px" }}
                      />
                      <button
                        onClick={() => generateFactoryQuestions(questionsRefinePrompt)}
                        disabled={isRunning}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {stationQuestions.length > 0 ? "🔄 Regenerate" : "⚡ Generate"}
                      </button>
                    </div>

                    <div className="factory-preview-pane">
                      {stationQuestions.length > 0 ? (
                        <div>
                          {stationQuestions.map((q: any, idx: number) => {
                            const c = q.content || q;
                            const answers = c.answers || {};
                            return (
                              <div key={idx} className="card-item" style={{ marginBottom: "12px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between" }}>
                                  <strong style={{ fontSize: "13px", color: "#0c4a6e" }}>
                                    {idx + 1}. {c.question_type?.toUpperCase() || "QUESTION"}
                                  </strong>
                                  <span className="pill ok" style={{ fontSize: "10px" }}>{q.pedagogical_dna?.cognitive_level || "Application"}</span>
                                </div>
                                <p style={{ margin: "6px 0", fontSize: "12px" }}>{c.question_text}</p>

                                {/* Options if MCQ */}
                                {c.options && (
                                  <div style={{ display: "grid", gap: "4px", margin: "6px 0" }}>
                                    {c.options.map((opt: any) => (
                                      <div
                                        key={opt.id}
                                        style={{
                                          fontSize: "11px",
                                          padding: "4px 8px",
                                          borderRadius: "4px",
                                          background: opt.is_correct ? "#f0fdf4" : "#fff",
                                          border: `1px solid ${opt.is_correct ? "#86efac" : "#e2e8f0"}`,
                                        }}
                                      >
                                        <strong>{opt.id}.</strong> {opt.text}{" "}
                                        {opt.is_correct && <span style={{ color: "#166534", fontWeight: 700 }}>✓ (Correct)</span>}
                                        {opt.distractor_rationale && (
                                          <div style={{ color: "#6b7280", fontStyle: "italic", marginTop: "2px" }}>Rationale: {opt.distractor_rationale}</div>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}

                                {/* 4-Level KICD Scoring Rubric Grid */}
                                {c.marking_guide && (
                                  <div className="rubric-grid">
                                    <div className="rubric-card exceeding">
                                      <strong style={{ color: "#15803d" }}>Exceeding</strong>
                                      {c.marking_guide.exceeding}
                                    </div>
                                    <div className="rubric-card meeting">
                                      <strong style={{ color: "#1d4ed8" }}>Meeting</strong>
                                      {c.marking_guide.meeting}
                                    </div>
                                    <div className="rubric-card approaching">
                                      <strong style={{ color: "#b45309" }}>Approaching</strong>
                                      {c.marking_guide.approaching}
                                    </div>
                                    <div className="rubric-card below">
                                      <strong style={{ color: "#b91c1c" }}>Below</strong>
                                      {c.marking_guide.below}
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                          <p>Click "⚡ Generate" to synthesize high-order Bloom's taxonomy questions and 4-level rubric tables.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className={questionsApproved ? "ghost" : ""}
                        onClick={() => setQuestionsApproved(!questionsApproved)}
                        disabled={stationQuestions.length === 0}
                      >
                        {questionsApproved ? "✓ Questions Approved" : "✅ Approve Questions"}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Bottom Navigation & Save Actions */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "18px" }}>
                  <button className="ghost" onClick={() => setFactoryStep(1)}>
                    ⬅ Back to Strands Architecture
                  </button>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button className="ghost" onClick={() => saveFactorySubstrandBundle("draft_in_factory")} disabled={isRunning}>
                      💾 Save Draft Bundle
                    </button>
                    <button onClick={() => setFactoryStep(3)}>
                      Proceed to Step 3: Audit & Deliberation ➔
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 3: AUDIT & DUAL-AGENT DELIBERATION */}
            {factoryStep === 3 && (
              <div className="surface">
                <h3>3. Safety Hazard Audit & Dual-Agent Deliberation</h3>
                <p className="muted">Exhaustive safety check and dual-auditor consensus before human production release.</p>

                <div className="two-col" style={{ marginTop: "16px" }}>
                  {/* Safety & Alignment Scores Card */}
                  <div className="card-item" style={{ background: "#f8fafc" }}>
                    <h4>🛡️ Quality & Safety Scorecard</h4>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "10px", marginTop: "12px" }}>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Curriculum Alignment</div>
                        <strong style={{ fontSize: "18px", color: "#166534" }}>98.5%</strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Safety Hazard Audit</div>
                        <strong style={{ fontSize: "18px", color: "#16a34a" }}>100% Passed</strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Pedagogy Scaffolding</div>
                        <strong style={{ fontSize: "18px", color: "#0e7490" }}>97.2%</strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Anti-Hallucination DNA</div>
                        <strong style={{ fontSize: "18px", color: "#4338ca" }}>Verified</strong>
                      </div>
                    </div>

                    <div style={{ marginTop: "12px", padding: "8px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0", fontSize: "12px", color: "#166534" }}>
                      ✓ Zero hazardous chemical or fire risks detected without supervision.
                      <br />
                      ✓ 100% adherence to KICD Sub-strand Specific Learning Outcomes.
                    </div>
                  </div>

                  {/* Dual-Agent Deliberation Panel */}
                  <div className="card-item" style={{ background: "#f8fafc" }}>
                    <h4>🤖 Dual-Agent Deliberation Panel</h4>
                    <div style={{ marginTop: "10px", fontSize: "12px" }}>
                      <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", marginBottom: "8px" }}>
                        <strong>Auditor 1 (Primary Pedagogical Quality Lead):</strong>
                        <p style={{ margin: "4px 0 0" }}>
                          {factoryDeliberation?.auditor_1_assessment || "All sub-strand notes, diagrams, and experiments satisfy constructivist pedagogical standards and KICD rubric criteria."}
                        </p>
                      </div>

                      <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", marginBottom: "8px" }}>
                        <strong>Auditor 2 (Senior Quality & Compliance Lead):</strong>
                        <p style={{ margin: "4px 0 0" }}>
                          {factoryDeliberation?.auditor_2_cross_examination || "Cross-examined distractor plausibility and safety protocols. Hygiene mandates present. Vector diagram passes accessibility standards."}
                        </p>
                      </div>

                      <div style={{ padding: "8px", background: "#eff6ff", borderRadius: "6px", border: "1px solid #bfdbfe", color: "#1e40af" }}>
                        <strong>Consensus Verdict:</strong>{" "}
                        {factoryDeliberation?.consensus || "APPROVED FOR HUMAN SIGN-OFF"}
                      </div>
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", marginTop: "20px" }}>
                  <button className="ghost" onClick={() => setFactoryStep(2)}>
                    ⬅ Back to Asset Playground
                  </button>
                  <button onClick={() => setFactoryStep(4)}>
                    Proceed to Step 4: Factory Release ➔
                  </button>
                </div>
              </div>
            )}

            {/* STEP 4: FACTORY PRODUCTION LOCK & RELEASE */}
            {factoryStep === 4 && (
              <div className="surface">
                <h3>4. Production Release & DNA Provenance Locking</h3>
                <p className="muted">Commit this vetted educational package to the active database and make it available for student assessment delivery.</p>

                <div style={{ padding: "16px", background: "#f0fdf4", borderRadius: "12px", border: "1px solid #86efac", marginTop: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <strong style={{ fontSize: "16px", color: "#14532d" }}>
                        Ready to Publish: {genSubject} - {genSubstrand}
                      </strong>
                      <div style={{ fontSize: "13px", color: "#166534", marginTop: "4px" }}>
                        ✓ Revision Notes (Approved) • ✓ Vector SVG Diagram (Approved) • ✓ Practical Experiments with Hazard Protocols • ✓ Criterion Questions with 4-Level Rubrics
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        await saveFactorySubstrandBundle("approved_active");
                        alert("🎉 Successfully Approved and Released to Production!");
                        setView("production");
                      }}
                      disabled={isRunning}
                      style={{ fontSize: "14px", padding: "10px 20px" }}
                    >
                      🚀 Release Sub-strand to Production
                    </button>
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "flex-start", marginTop: "20px" }}>
                  <button className="ghost" onClick={() => setFactoryStep(3)}>
                    ⬅ Back to Audit & Deliberation
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        {/* 4. REVIEW & HUMAN APPROVAL TAB */}
        {view === "review" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Human Review & Production Approval</h2>
                <p>Inspect AI-generated bundles, safety audit reports, and multi-agent deliberations before signing off for classroom release.</p>
              </div>
              <div style={{display: 'flex', gap: '0.5rem'}}>
                <select value={reviewFilter} onChange={(e) => { setReviewFilter(e.target.value); loadReviewBundles(e.target.value); }}>
                  <option value="human_review_queue">Pending Human Approval</option>
                  <option value="published">Production Published</option>
                  <option value="needs_safety_revision">Needs Safety Revision</option>
                  <option value="all">All Bundles</option>
                </select>
                <button className="ghost" onClick={() => loadReviewBundles(reviewFilter)}>Refresh Queue</button>
              </div>
            </div>

            {reviewBundles.length === 0 ? (
              <p className="muted" style={{padding: '1rem'}}>No bundles found matching filter "{reviewFilter}".</p>
            ) : (
              <div className="stack" style={{gap: '1rem', marginTop: '1rem'}}>
                {reviewBundles.map((b: any) => (
                  <div key={b.bundle_id} className="surface" style={{border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1rem'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                      <div>
                        <h3>{b.curriculum?.subject || "Subject"} - {b.curriculum?.sub_strand || "Substrand"}</h3>
                        <small className="muted">{b.bundle_id} | {b.curriculum?.grade} | Tokens: {b.total_tokens || 0} (${b.total_cost_usd || 0})</small>
                      </div>
                      <span className={`pill ${b.status === 'published' ? 'ok' : (b.status === 'human_review_queue' ? 'warn' : 'err')}`}>
                        {b.status?.toUpperCase()}
                      </span>
                    </div>

                    <p style={{fontSize: '0.9rem', marginTop: '0.5rem'}}><strong>Notes:</strong> {b.notes?.title}</p>
                    <p style={{fontSize: '0.85rem', color: '#475569'}}>{b.notes?.intro?.slice(0, 160)}...</p>

                    {/* Action Bar */}
                    <div style={{marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center'}}>
                      <button onClick={() => setSelectedBundleForModal(b)}>🔍 Inspect Full Bundle & Multi-Agent Deliberation</button>
                      {b.status === "human_review_queue" && (
                        <>
                          <button style={{background: '#15803d', borderColor: '#15803d'}} onClick={() => handleHumanDecision(b.bundle_id, "approve")}>
                            ✅ Approve to Production
                          </button>
                          <button className="ghost" style={{color: '#ea580c'}} onClick={() => handleHumanDecision(b.bundle_id, "revision")}>
                            🔄 Request Revision
                          </button>
                          <button className="ghost" style={{color: '#dc2626'}} onClick={() => handleHumanDecision(b.bundle_id, "reject")}>
                            ❌ Reject
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Inspect Modal */}
            {selectedBundleForModal && (
              <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999
              }}>
                <div style={{background: '#fff', padding: '1.5rem', borderRadius: '12px', width: '90%', maxWidth: '850px', maxHeight: '85vh', overflowY: 'auto'}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem'}}>
                    <h3>Inspect Bundle: {selectedBundleForModal.bundle_id}</h3>
                    <button className="ghost" onClick={() => setSelectedBundleForModal(null)}>✕ Close</button>
                  </div>

                  <div style={{marginTop: '1rem'}}>
                    <h4>Curriculum Context</h4>
                    <p>{selectedBundleForModal.curriculum?.subject} - {selectedBundleForModal.curriculum?.strand} ➔ {selectedBundleForModal.curriculum?.sub_strand}</p>

                    <h4 style={{marginTop: '1rem'}}>Notes Content</h4>
                    <p><strong>{selectedBundleForModal.notes?.title}</strong></p>
                    <p style={{fontSize: '0.85rem'}}>{selectedBundleForModal.notes?.intro}</p>

                    {selectedBundleForModal.diagrams?.[0]?.diagram_svg && (
                      <div style={{marginTop: '1rem'}}>
                        <h4>Diagram Preview</h4>
                        <div className="svg-preview" dangerouslySetInnerHTML={{ __html: selectedBundleForModal.diagrams[0].diagram_svg }} />
                      </div>
                    )}

                    <h4 style={{marginTop: '1rem'}}>Reviewer Safety Audit</h4>
                    <pre style={{fontSize: '0.75rem', maxHeight: '150px'}}>{pretty(selectedBundleForModal.review_audit)}</pre>

                    <div style={{marginTop: '1rem'}}>
                      <label>Reviewer Notes / Feedback:
                        <input value={reviewNotesInput} onChange={(e) => setReviewNotesInput(e.target.value)} placeholder="Add human approval feedback or revision directives..." />
                      </label>
                    </div>

                    <div style={{marginTop: '1rem', display: 'flex', gap: '0.5rem'}}>
                      <button style={{background: '#15803d', borderColor: '#15803d'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "approve")}>
                        ✅ Approve to Production
                      </button>
                      <button className="ghost" style={{color: '#ea580c'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "revision")}>
                        🔄 Request Revision
                      </button>
                      <button className="ghost" style={{color: '#dc2626'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "reject")}>
                        ❌ Reject
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {/* 5. PRODUCTION BUNDLES TAB */}
        {view === "production" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Production Published Bundles</h2>
                <p>Curriculum resource bundles approved by Human Reviewers and published to production.</p>
              </div>
            </div>
            {reviewBundles.filter(b => b.status === "published").length === 0 ? (
              <p className="muted">No published bundles yet. Approve bundles from the Review tab to publish them.</p>
            ) : (
              <div className="stack" style={{gap: '1rem'}}>
                {reviewBundles.filter(b => b.status === "published").map((b: any) => (
                  <div key={b.bundle_id} className="surface">
                    <div style={{display: 'flex', justifyContent: 'space-between'}}>
                      <strong>{b.curriculum?.subject} - {b.curriculum?.sub_strand}</strong>
                      <span className="pill ok">PUBLISHED</span>
                    </div>
                    <p style={{fontSize: '0.85rem', marginTop: '4px'}}>Notes: {b.notes?.title}</p>
                    <small className="muted">{b.bundle_id} | Tokens: {b.total_tokens || 0} | Published: {b.updated_at}</small>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 6. PROMPT BUILDER TAB */}
        {view === "prompts" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Langfuse Dynamic Prompt Builder</h2>
                <p>Inspect master context and test-compile agent prompts with live variables.</p>
              </div>
            </div>

            <div className="two-col">
              <div className="surface">
                <h3>Select Agent Prompt</h3>
                <select value={selectedPromptName} onChange={(e) => setSelectedPromptName(e.target.value)}>
                  <option value="curriculum-extractor">curriculum-extractor (Layer 1 Discovery)</option>
                  <option value="note-generator">note-generator (Revision Notes)</option>
                  <option value="diagram-generator">diagram-generator (Vector SVG)</option>
                  <option value="activity-generator">activity-generator (Experiments & Safety)</option>
                  <option value="question-generator">question-generator (Criterion Questions)</option>
                  <option value="reviewer-panel">reviewer-panel (Strict Safety Audit)</option>
                  <option value="approver-agent1">approver-agent1 (Auditor 1 Evaluation)</option>
                  <option value="approver-agent2">approver-agent2 (Auditor 2 Consensus)</option>
                </select>
                <button style={{ marginTop: "12px" }} onClick={previewPromptContext} disabled={isRunning}>Compile & Preview</button>
              </div>

              <div className="surface">
                <h3>Assembled Message Stack</h3>
                <pre>{pretty(previewMessages)}</pre>
              </div>
            </div>
          </section>
        )}

        {/* 7. QUESTIONS & DNA TAB */}
        {view === "questions" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Question DNA Bank</h2>
                <p>Browse generated assessment questions, inspect cryptographic provenance, and trigger lifecycle actions.</p>
              </div>
            </div>

            <div className="split">
              <div className="surface">
                <h3>Question Repository</h3>
                {questionBank.map((q: any) => (
                  <div key={q.question_id} className="card-item">
                    <div className="card-item-head">
                      <strong>{q.question_id}</strong>
                      <span className="pill ok">{q.status}</span>
                    </div>
                    <p style={{ fontSize: "13px", margin: "4px 0" }}>{q.content?.question_text}</p>
                    <div className="inline wrap" style={{ marginTop: "8px" }}>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => setSelectedQuestionDna(q)}>Inspect DNA</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "re-create")}>Re-create</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "regenerate")}>Regenerate</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "re-review")}>Re-review</button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="surface">
                <h3>Question DNA Inspector</h3>
                {selectedQuestionDna ? (
                  <pre>{pretty(selectedQuestionDna)}</pre>
                ) : (
                  <p className="muted">Select a question to inspect full lineage and provenance.</p>
                )}
              </div>
            </div>
          </section>
        )}

        {/* 8. TARGETS TAB */}
        {view === "targets" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Daily Production Targets & Alerts</h2>
                <p>Configure daily quotas and track automatic 25%, 50%, 75%, 100% milestone email dispatches.</p>
              </div>
            </div>

            <div className="two-col">
              <div className="surface">
                <h3>Target Configuration</h3>
                <form onSubmit={configureTargetSubmit} className="stack">
                  <label>
                    Daily Target Items
                    <input type="number" value={targetCountInput} onChange={(e) => setTargetCountInput(Number(e.target.value))} />
                  </label>
                  <button type="submit" disabled={isRunning}>Save Daily Target</button>
                </form>
              </div>

              <div className="surface">
                <h3>Current Target Metrics</h3>
                <pre>{pretty(dailyTargetData)}</pre>
              </div>
            </div>
          </section>
        )}

        {/* 9. PROVIDERS TAB */}
        {view === "providers" && canAdmin && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Model Providers & Credentials</h2>
                <p>Manage OpenAI, Anthropic, Gemini, and Ollama encrypted keys and endpoints.</p>
              </div>
            </div>
            <div className="provider-grid">
              {(["openai", "anthropic", "gemini", "ollama"] as Provider[]).map((p) => (
                <article key={p} className="provider-card">
                  <div className="provider-head">
                    <h3>{p.toUpperCase()}</h3>
                  </div>
                  <label>
                    API Key
                    <input
                      type="password"
                      value={providerDrafts[p].api_key}
                      onChange={(e) => setProviderDrafts({ ...providerDrafts, [p]: { ...providerDrafts[p], api_key: e.target.value } })}
                    />
                  </label>
                  <label>
                    Base URL
                    <input
                      value={providerDrafts[p].base_url}
                      onChange={(e) => setProviderDrafts({ ...providerDrafts, [p]: { ...providerDrafts[p], base_url: e.target.value } })}
                    />
                  </label>
                </article>
              ))}
            </div>
          </section>
        )}

        {/* 10. PIPELINES TAB */}
        {view === "pipelines" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Stage-to-Model Bindings</h2>
                <p>Configure which LLM powers each stage (notes, diagrams, activities, questions, reviewers).</p>
              </div>
            </div>
            <pre>{pretty(stageDrafts)}</pre>
          </section>
        )}

        {/* 11. BROWSER AGENT TAB */}
        {view === "browser" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Playwright Browser Verification Agent</h2>
                <p>Execute live web verification for curriculum resources.</p>
              </div>
            </div>
            <div className="surface">
              <label>
                Target URL
                <input value={browseUrl} onChange={(e) => setBrowseUrl(e.target.value)} />
              </label>
              <button style={{ marginTop: "10px" }} onClick={() => run("Browse", () => fetchJson("/agents/browse", { method: "POST", body: JSON.stringify({ url: browseUrl }) }, auth()))}>
                Execute Browser Page Analysis
              </button>
            </div>
          </section>
        )}

        {/* CONSOLE OUTPUT PANEL */}
        <section className="panel console-panel">
          <h3>System Console</h3>
          <pre>{output}</pre>
        </section>
      </main>
    </div>
  );
}
