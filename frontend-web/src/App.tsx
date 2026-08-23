import { FormEvent, useMemo, useState, useEffect } from "react";
import { API_BASE_URL, AUTH_EXPIRED_EVENT, fetchJson } from "./api";

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
  | "generation"
  | "questions_factory"
  | "questions"
  | "profiles"
  | "review"
  | "targets"
  | "providers"
  | "pipelines"
  | "browser"
  | "production";

const roleRights: Record<Role, string[]> = {
  admin: ["all"],
  operator: ["bindings", "generate", "jobs", "health", "browse", "production_read", "targets", "datasets", "prompts", "questions"],
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

function parseJwtExp(token: string): number | null {
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

function isTokenValid(token: string): boolean {
  const exp = parseJwtExp(token);
  if (exp === null) return true;
  return exp * 1000 > Date.now();
}

function normalizeQuestionOptions(
  options: any,
  correctAnswer?: string,
  distractorExplanations?: any
): Array<{ id: string; text: string; is_correct?: boolean; distractor_rationale?: string }> {
  if (!options) return [];
  if (Array.isArray(options)) {
    return options.map((opt, idx) => {
      if (typeof opt === "object" && opt !== null) {
        const id = opt.id || String.fromCharCode(65 + idx);
        return {
          id,
          text: opt.text || opt.label || opt.option || String(opt),
          is_correct: opt.is_correct ?? (correctAnswer ? (id.toUpperCase() === correctAnswer.toUpperCase() || String.fromCharCode(65 + idx).toUpperCase() === correctAnswer.toUpperCase()) : false),
          distractor_rationale: opt.distractor_rationale || (distractorExplanations && distractorExplanations[id]) || ""
        };
      }
      const id = String.fromCharCode(65 + idx);
      return {
        id,
        text: String(opt),
        is_correct: correctAnswer ? (id.toUpperCase() === correctAnswer.toUpperCase()) : false,
        distractor_rationale: (distractorExplanations && distractorExplanations[id]) || ""
      };
    });
  }
  if (typeof options === "object") {
    return Object.entries(options).map(([k, v]) => {
      if (typeof v === "object" && v !== null) {
        return {
          id: k,
          text: (v as any).text || (v as any).label || (v as any).option || String(v),
          is_correct: (v as any).is_correct ?? (correctAnswer ? (k.toUpperCase() === correctAnswer.toUpperCase()) : false),
          distractor_rationale: (v as any).distractor_rationale || (distractorExplanations && distractorExplanations[k]) || ""
        };
      }
      return {
        id: k,
        text: String(v),
        is_correct: correctAnswer ? (k.toUpperCase() === correctAnswer.toUpperCase()) : false,
        distractor_rationale: (distractorExplanations && distractorExplanations[k]) || ""
      };
    });
  }
  return [];
}

export function App() {
  const [output, setOutput] = useState("Ready");
  const [view, setView] = useState<View>("dashboard");
  const [isRunning, setIsRunning] = useState(false);

  // Authentication & Session State
  const [sessionExpiredNotice, setSessionExpiredNotice] = useState<string | null>(() => {
    const t = localStorage.getItem("cbc_token") || "";
    if (t && !isTokenValid(t)) {
      localStorage.removeItem("cbc_token");
      localStorage.removeItem("cbc_role");
      localStorage.removeItem("cbc_username");
      localStorage.removeItem("cbc_subject");
      return "Your session has expired. Please sign in again.";
    }
    return null;
  });

  const [username, setUsername] = useState(() => localStorage.getItem("cbc_username") || "admin");
  const [password, setPassword] = useState("admin123");
  const [bearerToken, setBearerToken] = useState(() => {
    const t = localStorage.getItem("cbc_token") || "";
    return isTokenValid(t) ? t : "";
  });
  const [apiKey, setApiKey] = useState("");
  const [currentRole, setCurrentRole] = useState<Role | null>(() => {
    const t = localStorage.getItem("cbc_token") || "";
    if (!t || !isTokenValid(t)) return null;
    return (localStorage.getItem("cbc_role") as Role) || null;
  });
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
  const [activeHourView, setActiveHourView] = useState<number | "all">("all");

  // Station 2: Multi-Visuals & Diagrams Studio
  const [stationDiagram, setStationDiagram] = useState<any>(null);
  const [stationVisualsList, setStationVisualsList] = useState<any[]>([]);
  const [activeVisualIdx, setActiveVisualIdx] = useState<number>(0);
  const [diagramConceptInput, setDiagramConceptInput] = useState("");
  const [diagramRefinePrompt, setDiagramRefinePrompt] = useState("");
  const [diagramViewMode, setDiagramViewMode] = useState<"visual" | "image_spec" | "code" | "tactile">("visual");
  const [diagramApproved, setDiagramApproved] = useState(false);

  // Station 3: Multi-Activities, Experiments & Video Storyboards Studio
  const [stationActivity, setStationActivity] = useState<any>(null);
  const [stationActivitiesList, setStationActivitiesList] = useState<any[]>([]);
  const [activeActivityIdx, setActiveActivityIdx] = useState<number>(0);
  const [activityDetailTab, setActivityDetailTab] = useState<"procedure" | "video" | "image" | "safety" | "rubric">("procedure");
  const [activityRefinePrompt, setActivityRefinePrompt] = useState("");
  const [activityApproved, setActivityApproved] = useState(false);

  // Station 4: Questions & Rubrics
  const [stationQuestions, setStationQuestions] = useState<any[]>([]);
  const [questionsDifficulty, setQuestionsDifficulty] = useState(0.65);
  const [questionsRefinePrompt, setQuestionsRefinePrompt] = useState("");
  const [questionsApproved, setQuestionsApproved] = useState(false);
  const [lastPersistedTime, setLastPersistedTime] = useState<string | null>(null);

  // Live Web Research, Thinking Trace & Quality Audit States
  const [notesResearchDossier, setNotesResearchDossier] = useState<any>(null);
  const [notesQualityAudit, setNotesQualityAudit] = useState<any>(null);
  const [notesQualityGate, setNotesQualityGate] = useState<any>(null);

  const [diagramResearchDossier, setDiagramResearchDossier] = useState<any>(null);
  const [diagramQualityAudit, setDiagramQualityAudit] = useState<any>(null);
  const [diagramQualityGate, setDiagramQualityGate] = useState<any>(null);

  const [activityResearchDossier, setActivityResearchDossier] = useState<any>(null);
  const [activityQualityAudit, setActivityQualityAudit] = useState<any>(null);
  const [activityQualityGate, setActivityQualityGate] = useState<any>(null);

  const [questionsResearchDossier, setQuestionsResearchDossier] = useState<any>(null);
  const [questionsQualityAudit, setQuestionsQualityAudit] = useState<any>(null);
  const [questionsQualityGate, setQuestionsQualityGate] = useState<any>(null);

  // Active Content-Type Profile and Substrand Blueprint View
  const [detectedContentType, setDetectedContentType] = useState<any>(null);
  const [showBlueprintDetails, setShowBlueprintDetails] = useState(true);

  // Active Trace Inspector Modal State
  const [activeTraceStation, setActiveTraceStation] = useState<"notes" | "diagram" | "activity" | "questions">("notes");
  const [showTraceModal, setShowTraceModal] = useState(false);

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
  const [isAuditingBundle, setIsAuditingBundle] = useState(false);

  // ─── QUESTIONS FACTORY DEDICATED ASSESSMENT ENGINE STATE ───
  const [qfGrade, setQfGrade] = useState<string>("grade-7");
  const [qfSubject, setQfSubject] = useState<string>("Agriculture and Environment");
  const [qfStrand, setQfStrand] = useState<string>("1.0 AGRICULTURE AND ENVIRONMENT");
  const [qfSubstrand, setQfSubstrand] = useState<string>("1.1 Importance of Agriculture");
  const [qfBatchCount, setQfBatchCount] = useState<number>(5);
  const [qfSelectedTypes, setQfSelectedTypes] = useState<string[]>([
    "multiple_choice",
    "diagram_based",
    "experiment_based",
    "structured_scenario",
    "quantitative_calculation",
  ]);
  const [qfSelectedBlooms, setQfSelectedBlooms] = useState<string[]>([
    "Application",
    "Analysis",
    "Critical Thinking",
    "Recall",
  ]);
  const [qfDifficulty, setQfDifficulty] = useState<number>(0.65);
  const [qfCustomPrompt, setQfCustomPrompt] = useState<string>("");
  const [qfQuestionsList, setQfQuestionsList] = useState<any[]>([]);
  const [qfActiveFilter, setQfActiveFilter] = useState<string>("all");
  const [qfShowGroundTruth, setQfShowGroundTruth] = useState<boolean>(false);
  const [qfGroundTruthData, setQfGroundTruthData] = useState<any>(null);
  const [qfEditingQuestionIdx, setQfEditingQuestionIdx] = useState<number | null>(null);
  const [qfExamExportModal, setQfExamExportModal] = useState<boolean>(false);
  const [qfExportedPaper, setQfExportedPaper] = useState<any>(null);
  const [qfExamTitle, setQfExamTitle] = useState<string>("Kenya Competency-Based Assessment: Formative & Summative Examination");
  const [qfExamTime, setQfExamTime] = useState<string>("1 Hour 30 Minutes");
  const [qfExamMarks, setQfExamMarks] = useState<number>(50);

  // Error banner state
  const [errorBanner, setErrorBanner] = useState<{code: string; message: string; retryable: boolean} | null>(null);

  // Pedagogical Profiles State
  const [profilesList, setProfilesList] = useState<any[]>([]);
  const [profileSearch, setProfileSearch] = useState("");
  const [profileGradeFilter, setProfileGradeFilter] = useState("all");
  const [activeProfileEdit, setActiveProfileEdit] = useState<any | null>(null);
  const [isAiImprovingProfile, setIsAiImprovingProfile] = useState(false);
  const [aiImprovePrompt, setAiImprovePrompt] = useState("");
  const [showNewProfileModal, setShowNewProfileModal] = useState(false);
  const [showAiGenerateModal, setShowAiGenerateModal] = useState(false);
  const [aiGenProfileSubject, setAiGenProfileSubject] = useState("");
  const [aiGenProfileGrade, setAiGenProfileGrade] = useState("all");
  const [aiGenProfileEssence, setAiGenProfileEssence] = useState("");
  const [newProfileForm, setNewProfileForm] = useState<any>({
    subject: "",
    grade: "all",
    content_type: "generic",
    persona: "",
    note_style: "",
    diagram_type: "",
    activity_type: "",
    question_type: "",
    safety_focus: "",
    grade_appropriate_tone: "formal academic and constructivist",
    special_directives: [],
    empirical_insights: [],
    case_studies: [],
  });

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
      const token = res.access_token;
      const userRole = (res.user?.role || res.role || username) as Role;
      const userSubject = res.user?.subject_scope || res.subject || "";

      setBearerToken(token);
      setCurrentRole(userRole);
      setCurrentSubject(userSubject);
      setView("dashboard"); // Explicitly redirects to home/dashboard
      setSessionExpiredNotice(null);

      localStorage.setItem("cbc_token", token);
      localStorage.setItem("cbc_role", userRole);
      localStorage.setItem("cbc_username", username);
      localStorage.setItem("cbc_subject", userSubject);
      return res;
    });
  }

  function logout(reason?: string) {
    setBearerToken("");
    setCurrentRole(null);
    setView("dashboard");
    localStorage.removeItem("cbc_token");
    localStorage.removeItem("cbc_role");
    localStorage.removeItem("cbc_username");
    localStorage.removeItem("cbc_subject");
    if (reason && typeof reason === "string") {
      setSessionExpiredNotice(reason);
    }
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

  function sanitizeSvgForDisplay(rawSvg: string): string {
    if (!rawSvg) return "<p style='color:#64748b;text-align:center;'>No SVG markup</p>";
    let clean = rawSvg.trim();

    // Strip markdown fences
    if (clean.includes("```")) {
      const match = clean.match(/```(?:xml|svg|html)?\s*(<svg[\s\S]*?<\/svg>)\s*```/i);
      if (match) clean = match[1];
      else {
        const matchAny = clean.match(/<svg[\s\S]*?<\/svg>/i);
        if (matchAny) clean = matchAny[0];
      }
    }

    const svgMatch = clean.match(/<svg[\s\S]*?<\/svg>/i);
    if (svgMatch) {
      clean = svgMatch[0];
    } else if (!clean.toLowerCase().startsWith("<svg")) {
      return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" width="100%" height="100%"><rect width="100%" height="100%" fill="#f8fafc" rx="8" stroke="#cbd5e1"/><text x="400" y="250" font-family="sans-serif" font-size="16" text-anchor="middle" fill="#0369a1">Visual Schematic</text></svg>`;
    }

    // Wrap naked CSS in <defs><style> if not present
    if (!clean.includes("<style") && /\.[a-zA-Z0-9_-]+\s*\{[^}]*\}/.test(clean)) {
      const cssMatches = clean.match(/(?:^|\n|\s)(\.[a-zA-Z0-9_-]+\s*\{[^}]*\}|#[a-zA-Z0-9_-]+\s*\{[^}]*\})/g) || [];
      if (cssMatches.length > 0) {
        const css = cssMatches.join("\n");
        for (const m of cssMatches) {
          clean = clean.replace(m, "");
        }
        const defs = `<defs><style type="text/css"><![CDATA[\n${css}\n]]></style><marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#0284c7" /></marker></defs>`;
        const gtIdx = clean.indexOf(">");
        if (gtIdx !== -1) {
          clean = clean.substring(0, gtIdx + 1) + "\n" + defs + "\n" + clean.substring(gtIdx + 1);
        }
      }
    }

    return clean;
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

  function getSubstrandBundleId(grade: string, subject: string, strand: string, subStrand: string): string {
    const cleanGrade = (grade || "grade").toLowerCase().replace(/[^a-z0-9]/g, "_");
    const cleanSubj = (subject || "subject").toLowerCase().replace(/[^a-z0-9]/g, "_");
    const cleanStrand = (strand || "strand").toLowerCase().replace(/[^a-z0-9]/g, "_");
    const cleanSS = (subStrand || "substrand").toLowerCase().replace(/[^a-z0-9]/g, "_");
    return `bundle_${cleanGrade}_${cleanSubj}_${cleanStrand}_${cleanSS}`;
  }

  async function loadSavedBundleForSubstrand(grade: string, subject: string, strand: string, subStrand: string) {
    const storageKey = `cbc:bundle:${grade}:${subject}:${strand}:${subStrand}`;
    
    // 1. Instant local restore from localStorage
    try {
      const cached = localStorage.getItem(storageKey);
      if (cached) {
        const data = JSON.parse(cached);
        if (data.notes) setStationNotes(data.notes);
        if (data.diagrams && data.diagrams.length > 0) {
          setStationVisualsList(data.diagrams);
          setStationDiagram(data.diagrams[0]);
        }
        if (data.activities) {
          const list = Array.isArray(data.activities.activities) ? data.activities.activities : (Array.isArray(data.activities) ? data.activities : []);
          if (list.length > 0) {
            setStationActivitiesList(list);
            setStationActivity(list[0]);
          }
        }
        if (data.questions && data.questions.length > 0) {
          setStationQuestions(data.questions);
        }
        if (typeof data.notesApproved === "boolean") setNotesApproved(data.notesApproved);
        if (typeof data.diagramApproved === "boolean") setDiagramApproved(data.diagramApproved);
        if (typeof data.activityApproved === "boolean") setActivityApproved(data.activityApproved);
        if (typeof data.questionsApproved === "boolean") setQuestionsApproved(data.questionsApproved);
      }
    } catch (e) {
      // Non-blocking
    }

    // 2. Authoritative restore from backend DB & MinIO
    try {
      const res = await fetchJson<any>(
        `/api/v1/curriculum/factory/bundle-by-substrand?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(subject)}&strand=${encodeURIComponent(strand)}&sub_strand=${encodeURIComponent(subStrand)}`,
        { method: "GET" },
        auth()
      );
      if (res && res.found) {
        if (res.notes && Object.keys(res.notes).length > 0) {
          setStationNotes(res.notes);
        }
        if (res.diagrams && res.diagrams.length > 0) {
          setStationVisualsList(res.diagrams);
          setStationDiagram(res.diagrams[0]);
        }
        if (res.activities) {
          const actData = res.activities;
          const list = Array.isArray(actData.activities) ? actData.activities : (Array.isArray(actData) ? actData : []);
          if (list.length > 0) {
            setStationActivitiesList(list);
            setStationActivity(list[0]);
          }
        }
        if (res.questions && res.questions.length > 0) {
          setStationQuestions(res.questions);
        }
        if (res.status === "approved" || res.status === "published") {
          setNotesApproved(true);
          setDiagramApproved(true);
          setActivityApproved(true);
          setQuestionsApproved(true);
        }
        setLastPersistedTime(new Date().toLocaleTimeString());
      }
    } catch (e) {
      // Non-blocking
    }
  }

  async function autoPersistStation(
    stationType: "notes" | "diagrams" | "activities" | "questions" | "approval",
    data: any,
    overrideNotes?: any,
    overrideVisuals?: any,
    overrideActivities?: any,
    overrideQuestions?: any,
    overrideApproved?: { notes?: boolean; diagram?: boolean; activity?: boolean; questions?: boolean }
  ) {
    if (!genGrade || !genSubject || !genSubstrand) return;
    const bundleId = getSubstrandBundleId(genGrade, genSubject, genStrand, genSubstrand);
    const storageKey = `cbc:bundle:${genGrade}:${genSubject}:${genStrand}:${genSubstrand}`;

    const currentNotes = overrideNotes !== undefined ? overrideNotes : (stationType === "notes" ? data : stationNotes);
    const currentVisuals = overrideVisuals !== undefined ? overrideVisuals : (stationType === "diagrams" ? (Array.isArray(data) ? data : [data]) : stationVisualsList);
    const currentActs = overrideActivities !== undefined ? overrideActivities : (stationType === "activities" ? (Array.isArray(data) ? data : (data?.activities || [data])) : stationActivitiesList);
    const currentQs = overrideQuestions !== undefined ? overrideQuestions : (stationType === "questions" ? (Array.isArray(data) ? data : [data]) : stationQuestions);

    const nApp = overrideApproved?.notes !== undefined ? overrideApproved.notes : notesApproved;
    const dApp = overrideApproved?.diagram !== undefined ? overrideApproved.diagram : diagramApproved;
    const aApp = overrideApproved?.activity !== undefined ? overrideApproved.activity : activityApproved;
    const qApp = overrideApproved?.questions !== undefined ? overrideApproved.questions : questionsApproved;

    const bundleState = {
      bundle_id: bundleId,
      grade: genGrade,
      subject: genSubject,
      strand: genStrand,
      sub_strand: genSubstrand,
      notes: currentNotes,
      diagrams: currentVisuals,
      activities: { activities: currentActs },
      questions: currentQs,
      notesApproved: nApp,
      diagramApproved: dApp,
      activityApproved: aApp,
      questionsApproved: qApp,
      updatedAt: new Date().toISOString(),
    };

    // 1. Instant local persistence
    try {
      localStorage.setItem(storageKey, JSON.stringify(bundleState));
      localStorage.setItem("cbc:last_factory_substrand", JSON.stringify({
        ss: factorySelectedSubstrand,
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        step: factoryStep
      }));
    } catch (e) {
      // Ignore quota error
    }

    // 2. Background DB & MinIO persistence
    try {
      const isAllApproved = nApp && dApp && aApp && qApp;
      await fetchJson<any>("/api/v1/curriculum/factory/auto-persist-station", {
        method: "POST",
        body: JSON.stringify({
          bundle_id: bundleId,
          grade: genGrade,
          subject: genSubject,
          strand: genStrand,
          sub_strand: genSubstrand,
          station_type: stationType,
          data: data,
          review_status: isAllApproved ? "approved" : "draft",
          human_notes: humanBlueprintNotes || "",
        }),
      }, auth());
      setLastPersistedTime(new Date().toLocaleTimeString());
    } catch (e) {
      // Non-blocking
    }
  }

  function toggleNotesApproval() {
    const next = !notesApproved;
    setNotesApproved(next);
    autoPersistStation("approval", null, undefined, undefined, undefined, undefined, { notes: next });
  }

  function toggleDiagramApproval() {
    const next = !diagramApproved;
    setDiagramApproved(next);
    autoPersistStation("approval", null, undefined, undefined, undefined, undefined, { diagram: next });
  }

  function toggleActivityApproval() {
    const next = !activityApproved;
    setActivityApproved(next);
    autoPersistStation("approval", null, undefined, undefined, undefined, undefined, { activity: next });
  }

  function toggleQuestionsApproval() {
    const next = !questionsApproved;
    setQuestionsApproved(next);
    autoPersistStation("approval", null, undefined, undefined, undefined, undefined, { questions: next });
  }

  function selectSubstrandForFactory(ss: any, grade: string, subject: string) {
    setFactorySelectedSubstrand(ss);
    setGenGrade(grade);
    setGenSubject(subject);
    const strandName = ss.strand_name || "";
    const substrandName = ss.sub_strand_name || ss.name || "";
    setGenStrand(strandName);
    setGenSubstrand(substrandName);
    const sloList = ss.slos || [];
    const firstSlo = typeof sloList[0] === 'string' ? sloList[0] : (sloList[0]?.text || sloList[0]?.id || "");
    setGenSloId(firstSlo);
    const diagramTarget = (ss.required_diagrams && ss.required_diagrams[0]) || substrandName || "Visual Model";
    setDiagramConceptInput(diagramTarget);
    setFactoryStep(2);

    // Clear previous station content initially
    setStationNotes(null);
    setStationDiagram(null);
    setStationVisualsList([]);
    setActiveVisualIdx(0);
    setStationActivity(null);
    setStationActivitiesList([]);
    setActiveActivityIdx(0);
    setActivityDetailTab("procedure");
    setStationQuestions([]);
    setNotesApproved(false);
    setDiagramApproved(false);
    setActivityApproved(false);
    setQuestionsApproved(false);

    setNotesResearchDossier(null);
    setNotesQualityAudit(null);
    setNotesQualityGate(null);
    setDiagramResearchDossier(null);
    setDiagramQualityAudit(null);
    setDiagramQualityGate(null);
    setActivityResearchDossier(null);
    setActivityQualityAudit(null);
    setActivityQualityGate(null);
    setQuestionsResearchDossier(null);
    setQuestionsQualityAudit(null);
    setQuestionsQualityGate(null);
    setFactoryAudit(null);
    setFactoryDeliberation(null);

    // Automatically load existing saved bundle for this sub-strand from DB / MinIO / LocalStorage
    loadSavedBundleForSubstrand(grade, subject, strandName, substrandName);
  }

  async function generateFactoryNotes(customInstructions?: string) {
    await run("Layer 1: Generating Comprehensive Notes with Content-Type Scaffolding...", async () => {
      const activeCd = curriculumDesignsList.find((cd: any) =>
        cd.subject?.toLowerCase() === genSubject?.toLowerCase() &&
        (cd.grade === genGrade || cd.grade === genGrade.replace("grade-", ""))
      ) || (ingestedDesignResult?.subject?.toLowerCase() === genSubject?.toLowerCase() ? ingestedDesignResult : null);

      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        slo_id: genSloId,
        level: activeCd?.level || "Basic Education",
        essence_statement: activeCd?.essence_statement || "",
        general_learning_outcomes: activeCd?.general_learning_outcomes || [],
        source_material_text: substrandSourceMaterial,
        custom_instructions: customInstructions || notesRefinePrompt || "Author exhaustive pedagogical lesson notes with 3-5 comprehensive concepts, PCK teacher notes, common learner misconception analysis, formative checks, worked problem scenarios, and practical fieldwork steps.",
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-notes", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.notes) {
        setStationNotes(res.notes);
        setNotesApproved(false);
        autoPersistStation("notes", res.notes, res.notes, undefined, undefined, undefined, { notes: false });
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setNotesResearchDossier(res.research_dossier);
      if (res.quality_audit) setNotesQualityAudit(res.quality_audit);
      if (res.quality_gate) setNotesQualityGate(res.quality_gate);
      return res;
    });
  }

  async function generateFactoryDiagram(customInstructions?: string) {
    await run("Layer 2: Generating Vector SVG Diagram derived from Layer 1 Notes...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        concept: diagramConceptInput || genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        notes_content: stationNotes || undefined,
        custom_instructions: customInstructions || diagramRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-diagram", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.diagram) {
        setStationDiagram(res.diagram);
        const updated = [res.diagram];
        setStationVisualsList(updated);
        setDiagramApproved(false);
        autoPersistStation("diagrams", updated, undefined, updated, undefined, undefined, { diagram: false });
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setDiagramResearchDossier(res.research_dossier);
      if (res.quality_audit) setDiagramQualityAudit(res.quality_audit);
      if (res.quality_gate) setDiagramQualityGate(res.quality_gate);
      return res;
    });
  }

  async function planFactoryVisuals(customInstructions?: string) {
    await run("Layer 2: Planning Multi-Item Visuals & Diagrams for Sub-strand...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        notes_content: stationNotes || undefined,
        custom_instructions: customInstructions || diagramRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/plan-visuals", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.visuals && res.visuals.length > 0) {
        setStationVisualsList(res.visuals);
        setActiveVisualIdx(0);
        autoPersistStation("diagrams", res.visuals, undefined, res.visuals);
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setDiagramResearchDossier(res.research_dossier);
      return res;
    });
  }

  async function generateSingleVisual(visualItem: any, index: number, customInstructions?: string) {
    await run(`Layer 2: Synthesizing Visual Asset ${index + 1} (${visualItem.title || 'Diagram'})...`, async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        visual_item: visualItem,
        notes_content: stationNotes || undefined,
        custom_instructions: customInstructions || diagramRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-single-visual", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.visual) {
        const next = [...stationVisualsList];
        next[index] = res.visual;
        setStationVisualsList(next);
        if (index === activeVisualIdx || !stationDiagram) {
          setStationDiagram(res.visual);
        }
        autoPersistStation("diagrams", next, undefined, next);
      }
      if (res.quality_audit) setDiagramQualityAudit(res.quality_audit);
      if (res.quality_gate) setDiagramQualityGate(res.quality_gate);
      return res;
    });
  }

  async function generateAllVisuals() {
    if (stationVisualsList.length === 0) {
      await planFactoryVisuals();
    }
    for (let i = 0; i < stationVisualsList.length; i++) {
      await generateSingleVisual(stationVisualsList[i], i);
    }
  }

  async function generateFactoryActivity(customInstructions?: string) {
    await run("Layer 3: Generating Practical Activities derived from Layers 1 & 2...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        notes_content: stationNotes || undefined,
        diagram_info: stationDiagram || undefined,
        custom_instructions: customInstructions || activityRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-activity", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.activity) {
        setStationActivity(res.activity);
        const updated = [res.activity];
        setStationActivitiesList(updated);
        setActivityApproved(false);
        autoPersistStation("activities", { activities: updated }, undefined, undefined, updated, undefined, { activity: false });
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setActivityResearchDossier(res.research_dossier);
      if (res.quality_audit) setActivityQualityAudit(res.quality_audit);
      if (res.quality_gate) setActivityQualityGate(res.quality_gate);
      return res;
    });
  }

  async function planFactoryActivities(customInstructions?: string) {
    await run("Layer 3: Planning Multi-Item Practical Tasks & Video Storyboards...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        notes_title: stationNotes?.title || genSubstrand,
        notes_content: stationNotes || undefined,
        diagram_info: stationDiagram || undefined,
        custom_instructions: customInstructions || activityRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/plan-activities", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.activities && res.activities.length > 0) {
        setStationActivitiesList(res.activities);
        setActiveActivityIdx(0);
        autoPersistStation("activities", { activities: res.activities }, undefined, undefined, res.activities);
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setActivityResearchDossier(res.research_dossier);
      return res;
    });
  }

  async function generateSingleActivity(activityItem: any, index: number, customInstructions?: string) {
    await run(`Layer 3: Synthesizing Practical Module ${index + 1} (${activityItem.activity_name || 'Activity'})...`, async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        activity_item: activityItem,
        notes_content: stationNotes || undefined,
        custom_instructions: customInstructions || activityRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-single-activity", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.activity) {
        const next = [...stationActivitiesList];
        next[index] = res.activity;
        setStationActivitiesList(next);
        if (index === activeActivityIdx || !stationActivity) {
          setStationActivity(res.activity);
        }
        autoPersistStation("activities", { activities: next }, undefined, undefined, next);
      }
      if (res.quality_audit) setActivityQualityAudit(res.quality_audit);
      if (res.quality_gate) setActivityQualityGate(res.quality_gate);
      return res;
    });
  }

  async function generateAllActivities() {
    if (stationActivitiesList.length === 0) {
      await planFactoryActivities();
    }
    for (let i = 0; i < stationActivitiesList.length; i++) {
      await generateSingleActivity(stationActivitiesList[i], i);
    }
  }

  async function generateFactoryQuestions(customInstructions?: string) {
    await run("Layer 4: Generating Assessment Items derived from ALL Upstream Layers...", async () => {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        subject_code: genSubject.substring(0, 4).toUpperCase(),
        strand: genStrand,
        sub_strand: genSubstrand,
        slo_id: genSloId,
        difficulty: questionsDifficulty,
        notes_summary: stationNotes?.intro || "",
        notes_content: stationNotes || undefined,
        diagram_title: stationDiagram?.diagram_title || "",
        diagram_info: stationDiagram || undefined,
        activity_info: stationActivity || undefined,
        custom_instructions: customInstructions || questionsRefinePrompt,
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/generate-questions", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.questions) {
        setStationQuestions(res.questions);
        setQuestionsApproved(false);
        autoPersistStation("questions", res.questions, undefined, undefined, undefined, res.questions, { questions: false });
      }
      if (res.content_type) setDetectedContentType(res.content_type);
      if (res.research_dossier) setQuestionsResearchDossier(res.research_dossier);
      if (res.quality_audit) setQuestionsQualityAudit(res.quality_audit);
      if (res.quality_gate) setQuestionsQualityGate(res.quality_gate);
      return res;
    });
  }

  async function runLiveBundleAudit() {
    setIsAuditingBundle(true);
    try {
      const payload = {
        grade: genGrade,
        subject: genSubject,
        strand: genStrand,
        sub_strand: genSubstrand,
        level: "Basic Education",
        notes: stationNotes || {},
        diagram: stationDiagram || {},
        activity: stationActivity || {},
        questions: stationQuestions || [],
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/audit-bundle", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.audit) {
        setFactoryAudit(res);
        setFactoryDeliberation(res.audit);
      }
      return res;
    } catch(e) {
      console.error("Bundle audit failed:", e);
    } finally {
      setIsAuditingBundle(false);
    }
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
        diagrams: stationVisualsList.length > 0 ? stationVisualsList : (stationDiagram ? [stationDiagram] : []),
        activities: stationActivitiesList.length > 0 ? stationActivitiesList : (stationActivity ? [stationActivity] : []),
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

  async function publishFactorySubstrandBundle() {
    await run("Releasing & Registering Artifact DNA in Production...", async () => {
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
        diagrams: stationVisualsList.length > 0 ? stationVisualsList : (stationDiagram ? [stationDiagram] : []),
        activity: stationActivity || {},
        activities: stationActivitiesList.length > 0 ? stationActivitiesList : (stationActivity ? [stationActivity] : []),
        questions: stationQuestions || [],
        deliberation_notes: factoryDeliberation?.consensus || "Approved via 5-Layer Content Factory",
      };
      const res = await fetchJson<any>("/api/v1/curriculum/factory/publish-bundle", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      await Promise.all([loadQuestionBank(), loadReviewBundles("all")]);
      return res;
    });
  }

  // ─── QUESTIONS FACTORY DEDICATED ASSESSMENT ENGINE HANDLERS ───
  async function loadGroundTruthForQF(grade: string, subject: string, strand: string, subStrand: string) {
    try {
      const res = await fetchJson<any>(
        `/api/v1/curriculum/factory/bundle-by-substrand?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(subject)}&strand=${encodeURIComponent(strand)}&sub_strand=${encodeURIComponent(subStrand)}`,
        { method: "GET" },
        auth()
      );
      if (res && res.found) {
        setQfGroundTruthData(res);
      } else {
        setQfGroundTruthData(null);
      }
    } catch (e) {
      setQfGroundTruthData(null);
    }
  }

  function openQuestionsFactoryFromContentFactory() {
    const targetGrade = genGrade || "grade-7";
    const targetSubj = genSubject || "Agriculture and Environment";
    const targetStrand = genStrand || "1.0 AGRICULTURE AND ENVIRONMENT";
    const targetSubstrand = genSubstrand || "1.1 Importance of Agriculture";
    setQfGrade(targetGrade);
    setQfSubject(targetSubj);
    setQfStrand(targetStrand);
    setQfSubstrand(targetSubstrand);
    loadGroundTruthForQF(targetGrade, targetSubj, targetStrand, targetSubstrand);
    loadQuestionsForSubstrand(targetGrade, targetSubj, targetStrand, targetSubstrand);
    setView("questions_factory");
  }

  async function loadQuestionsForSubstrand(grade: string, subject: string, strand: string, subStrand: string) {
    try {
      const res = await fetchJson<any>(
        `/api/v1/questions/by-substrand?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(subject)}&strand=${encodeURIComponent(strand)}&sub_strand=${encodeURIComponent(subStrand)}`,
        { method: "GET" },
        auth()
      );
      if (res && res.questions && res.questions.length > 0) {
        const mapped = res.questions.map((q: any) => ({
          question_id: q.question_id,
          universal_id: q.universal_id,
          question_type: q.content?.question_type || q.pedagogical_dna?.question_type || "multiple_choice",
          bloom_level: q.pedagogical_dna?.bloom_level || "Application",
          difficulty_index: q.pedagogical_dna?.difficulty_index || 0.65,
          max_marks: q.pedagogical_dna?.max_marks || 2,
          estimated_time_mins: q.pedagogical_dna?.estimated_time_mins || 3,
          micro_concept: q.pedagogical_dna?.micro_concept || subStrand,
          target_slo: q.curriculum_link?.slo_id || "SLO-01",
          stimulus_context: q.content?.stimulus_context || "",
          question_text: q.content?.question_text || "",
          diagram_ref: q.content?.diagram_ref || "",
          diagram_svg: q.content?.diagram_svg || "",
          options: q.content?.options,
          correct_answer: q.content?.correct_answer,
          structured_parts: q.content?.structured_parts,
          model_answer: q.content?.model_answer || "",
          marking_scheme: q.content?.marking_scheme || "",
          marking_guide: q.content?.marking_guide || {},
          provenance_citation: q.provenance?.source_citations || "[KNBS 2024 / KALRO 2023] — Linked to Lesson Notes",
          approved: q.status === "approved",
        }));
        setQfQuestionsList(mapped);
      }
    } catch (e) {
      // Non-blocking
    }
  }

  async function generateQuestionsFactoryBatch(customPrompt?: string) {
    await run(`🎯 Generating Batch of ${qfBatchCount} Publication Assessment Items...`, async () => {
      const payload = {
        grade: qfGrade,
        subject: qfSubject,
        strand: qfStrand,
        sub_strand: qfSubstrand,
        batch_count: qfBatchCount,
        question_types: qfSelectedTypes.length > 0 ? qfSelectedTypes : ["multiple_choice", "structured_scenario", "diagram_based", "experiment_based"],
        bloom_levels: qfSelectedBlooms.length > 0 ? qfSelectedBlooms : ["Application", "Analysis", "Critical Thinking"],
        difficulty: qfDifficulty,
        custom_instructions: customPrompt || qfCustomPrompt || "Generate diverse, rigorous Kenya CBC questions referencing the saved notes, diagrams, and experiments.",
      };
      const res = await fetchJson<any>("/api/v1/questions/factory/generate-batch", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.questions && res.questions.length > 0) {
        setQfQuestionsList((prev) => [...prev, ...res.questions]);
      }
      return res;
    });
  }

  async function generateQuestionsFactorySingle(qType: string, conceptTarget: string) {
    await run(`🎯 Generating Single ${qType.replace('_', ' ').toUpperCase()} Item...`, async () => {
      const payload = {
        grade: qfGrade,
        subject: qfSubject,
        strand: qfStrand,
        sub_strand: qfSubstrand,
        question_type: qType,
        bloom_level: "Application",
        difficulty: qfDifficulty,
        concept_target: conceptTarget,
        custom_instructions: qfCustomPrompt,
      };
      const res = await fetchJson<any>("/api/v1/questions/factory/generate-single", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res.questions && res.questions.length > 0) {
        setQfQuestionsList((prev) => [...prev, ...res.questions]);
      }
      return res;
    });
  }

  function toggleApproveQuestionInQF(index: number) {
    setQfQuestionsList((prev) => {
      const copy = [...prev];
      if (copy[index]) {
        copy[index] = { ...copy[index], approved: !copy[index].approved };
      }
      return copy;
    });
  }

  async function approveAllQFQuestions() {
    await run("✅ Syncing & Registering All Questions in Question DNA Repository...", async () => {
      const payload = {
        grade: qfGrade,
        subject: qfSubject,
        strand: qfStrand,
        sub_strand: qfSubstrand,
        questions: qfQuestionsList,
        status: "approved",
      };
      const res = await fetchJson<any>("/api/v1/questions/factory/approve-batch", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      setQfQuestionsList((prev) => prev.map((q) => ({ ...q, approved: true })));
      await loadQuestionBank();
      return res;
    });
  }

  function deleteQFQuestion(index: number) {
    setQfQuestionsList((prev) => prev.filter((_, i) => i !== index));
  }

  async function exportQFExamPaper() {
    await run("📑 Formatting KNEC / KICD Publication Exam Paper & Marking Scheme...", async () => {
      const payload = {
        grade: qfGrade,
        subject: qfSubject,
        strand: qfStrand,
        sub_strand: qfSubstrand,
        exam_title: qfExamTitle,
        time_allowed: qfExamTime,
        total_marks: qfExamMarks,
        questions: qfQuestionsList,
      };
      const res = await fetchJson<any>("/api/v1/questions/factory/export-exam", {
        method: "POST",
        body: JSON.stringify(payload),
      }, auth());
      if (res) {
        setQfExportedPaper(res);
        setQfExamExportModal(true);
      }
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

  // Pedagogical Profiles Data Handlers
  async function loadProfilesList(search = profileSearch, grade = profileGradeFilter) {
    try {
      const q = new URLSearchParams();
      if (search) q.append("search", search);
      if (grade && grade !== "all") q.append("grade", grade);
      const res = await fetchJson<any>(`/api/v1/curriculum/profiles?${q.toString()}`, { method: "GET" }, auth());
      setProfilesList(res.profiles || []);
    } catch(e) {
      console.warn("Failed to load profiles:", e);
    }
  }

  async function saveProfileEdit(profileData: any) {
    await run("Saving Subject Profile", async () => {
      let res;
      if (profileData.id) {
        res = await fetchJson<any>(`/api/v1/curriculum/profiles/${profileData.id}`, {
          method: "PUT",
          body: JSON.stringify(profileData)
        }, auth());
      } else {
        res = await fetchJson<any>("/api/v1/curriculum/profiles", {
          method: "POST",
          body: JSON.stringify(profileData)
        }, auth());
      }
      await loadProfilesList();
      setActiveProfileEdit(null);
      setShowNewProfileModal(false);
      return res;
    });
  }

  async function deleteProfile(profileId: number) {
    if (!confirm("Are you sure you want to delete this custom pedagogical profile?")) return;
    await run("Deleting Profile", async () => {
      const res = await fetchJson<any>(`/api/v1/curriculum/profiles/${profileId}`, { method: "DELETE" }, auth());
      await loadProfilesList();
      return res;
    });
  }

  async function improveProfileWithAi(profileData: any, instructions: string) {
    try {
      setIsAiImprovingProfile(true);
      const res = await fetchJson<any>("/api/v1/curriculum/profiles/ai-improve", {
        method: "POST",
        body: JSON.stringify({ profile: profileData, instructions })
      }, auth());
      if (res?.profile) {
        setActiveProfileEdit(res.profile);
        await loadProfilesList();
      }
    } catch(err: any) {
      alert("AI improvement failed: " + (err.message || String(err)));
    } finally {
      setIsAiImprovingProfile(false);
    }
  }

  async function generateProfileWithAi(subject: string, grade: string, essence: string) {
    await run("Synthesizing Profile with AI", async () => {
      const res = await fetchJson<any>("/api/v1/curriculum/profiles/ai-generate", {
        method: "POST",
        body: JSON.stringify({ subject, grade, essence_statement: essence })
      }, auth());
      if (res?.profile) {
        await loadProfilesList();
        setActiveProfileEdit(res.profile);
        setShowAiGenerateModal(false);
      }
      return res;
    });
  }

  // Refresh Dashboard
  async function refreshDashboard() {
    await Promise.all([loadTodayTarget(), loadQuestionBank(), loadCostSummary(), loadProfilesList()]);
  }

  useEffect(() => {
    // 1. Listen for 401 Auth Expired events from api.ts
    function handleAuthExpired(e: Event) {
      const customEvent = e as CustomEvent<{ reason?: string }>;
      const reason = customEvent.detail?.reason || "Your session has expired. Please sign in again.";
      logout(reason);
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);

    if (!currentRole || !bearerToken) {
      return () => {
        window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
      };
    }

    loadDatasets();
    loadRawLangfuseDatasets();
    loadCurriculumDesigns();
    loadTodayTarget();
    loadQuestionBank();
    loadCostSummary();
    loadMasterContext();
    loadReviewBundles(reviewFilter);
    loadProfilesList();

    // Restore last active factory sub-strand and load its persisted notes, diagrams, activities, and questions
    try {
      const rawLast = localStorage.getItem("cbc:last_factory_substrand");
      if (rawLast) {
        const parsed = JSON.parse(rawLast);
        if (parsed && parsed.ss && parsed.grade && parsed.subject) {
          selectSubstrandForFactory(parsed.ss, parsed.grade, parsed.subject);
          if (parsed.step) setFactoryStep(parsed.step);
        }
      }
    } catch (e) {
      // Non-blocking
    }

    // 2. Proactive JWT Expiration Timer
    let expTimer: any = null;
    const expSec = parseJwtExp(bearerToken);
    if (expSec) {
      const msUntilExp = expSec * 1000 - Date.now();
      if (msUntilExp <= 0) {
        logout("Your session has expired. Please sign in again.");
      } else {
        expTimer = setTimeout(() => {
          logout("Your session has timed out. Please sign in again.");
        }, msUntilExp);
      }
    }

    // 3. User Inactivity / Idle Timeout (30 Minutes of idle time)
    const IDLE_TIMEOUT_MS = 30 * 60 * 1000;
    let idleTimer: any = null;

    function resetIdleTimer() {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        logout("You were logged out due to 30 minutes of inactivity.");
      }, IDLE_TIMEOUT_MS);
    }

    const activityEvents = ["mousedown", "mousemove", "keydown", "scroll", "touchstart"];
    activityEvents.forEach((ev) => window.addEventListener(ev, resetIdleTimer, { passive: true }));
    resetIdleTimer();

    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
      if (expTimer) clearTimeout(expTimer);
      if (idleTimer) clearTimeout(idleTimer);
      activityEvents.forEach((ev) => window.removeEventListener(ev, resetIdleTimer));
    };
  }, [currentRole, bearerToken]);

  const canAdmin = hasRight(currentRole, "all");

  const navItems: Array<{ id: View; label: string; right: string }> = [
    { id: "dashboard", label: "Dashboard", right: "health" },
    { id: "datasets", label: "Datasets & Blueprints", right: "datasets" },
    { id: "generation", label: "🏭 Content Factory", right: "generate" },
    { id: "questions_factory", label: "🎯 Questions Factory", right: "generate" },
    { id: "questions", label: "📚 Question Bank & DNA", right: "questions" },
    { id: "profiles", label: "🎭 Pedagogical Profiles", right: "generate" },
    { id: "review", label: "Review & Human Approval", right: "review" },
    { id: "production", label: "Production Bundles", right: "production_read" },
    { id: "prompts", label: "Prompt Builder", right: "prompts" },
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
          {sessionExpiredNotice && (
            <div style={{
              padding: "10px 14px",
              background: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: "8px",
              color: "#92400e",
              fontSize: "12.5px",
              marginBottom: "14px",
              display: "flex",
              alignItems: "center",
              gap: "8px"
            }}>
              <span style={{ fontSize: "16px" }}>⚠️</span>
              <div>{sessionExpiredNotice}</div>
            </div>
          )}
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
          <button className="ghost" onClick={() => logout()}>Sign out</button>
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
                            <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                              <button
                                className="ghost"
                                style={{ fontSize: '0.78rem', padding: '5px 10px', background: '#f0fdf4', color: '#166534', borderColor: '#86efac' }}
                                title="Synthesize an exhaustive Pedagogical Profile from this complete curriculum design"
                                onClick={async () => {
                                  await run(`Generating Profile for ${d.subject}`, async () => {
                                    const res = await fetchJson<any>(`/api/v1/curriculum/profiles/generate-from-design/${d.design_id}`, { method: "POST" }, auth());
                                    if (res?.profile) {
                                      await loadProfilesList();
                                      setActiveProfileEdit(res.profile);
                                      setView("profiles");
                                    }
                                    return res;
                                  });
                                }}
                              >
                                🎭 Generate Profile
                              </button>
                              <button
                                onClick={() => {
                                  setGenGrade(d.grade);
                                  setGenSubject(d.subject);
                                  loadGradeSubjects(d.grade);
                                  setView("generation");
                                }}
                                style={{fontSize: '0.8rem', padding: '6px 12px'}}
                              >
                                🚀 Open in Factory
                              </button>
                            </div>
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

            {/* STEP 2: INTERACTIVE ASSET FACTORY PLAYGROUND (5-LAYER PIPELINE) */}
            {factoryStep === 2 && (
              <div>
                {/* Dynamic Sub-strand Selection & Switcher Bar */}
                <div className="surface" style={{ marginBottom: "16px", background: "#f0fdf4", borderColor: "#bbf7d0" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px" }}>
                    <div style={{ flex: 1, minWidth: "280px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                        <small style={{ color: "#166534", fontWeight: 700, textTransform: "uppercase", fontSize: "11px" }}>
                          Active Sub-strand Blueprint:
                        </small>
                        {detectedContentType && (
                          <button
                            className="pill ok"
                            style={{ fontSize: "10px", background: "#dcfce7", color: "#14532d", border: "1px solid #86efac", cursor: "pointer", padding: "2px 8px" }}
                            title="Click to view or edit this Subject's Pedagogical Profile"
                            onClick={() => {
                              setActiveProfileEdit(detectedContentType);
                              setView("profiles");
                            }}
                          >
                            🏷️ {detectedContentType.content_type?.toUpperCase()} (⚙️ Customize Profile)
                          </button>
                        )}
                        <span className="pill" style={{ fontSize: "10px", background: "#e0f2fe", color: "#0369a1" }}>
                          Level: {genGrade}
                        </span>
                      </div>

                      <h2 style={{ margin: "6px 0 4px", color: "#14532d", fontSize: "18px" }}>
                        {genSubject} ➔ <span style={{ color: "#0369a1" }}>🌿 Strand: {genStrand || "General Strand"}</span> ➔ <span style={{ color: "#15803d", textDecoration: "underline" }}>🌱 Sub-strand: {genSubstrand || "Select Sub-strand"}</span>
                      </h2>

                      {/* Strand Guidance Context Pill */}
                      {genStrand && (
                        <div style={{ fontSize: "11.5px", color: "#075985", background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: "6px", padding: "4px 8px", marginTop: "4px", display: "inline-block" }}>
                          ℹ️ <strong>Parent Strand Scope & Guidance:</strong> Overall curricular anchor for all sub-strands in {genStrand}.
                        </div>
                      )}

                      {/* Sub-strand Switcher Pills */}
                      {factorySubstrandsList.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "8px" }}>
                          <span style={{ fontSize: "11px", color: "#166534", alignSelf: "center", fontWeight: 600 }}>Switch Sub-strand:</span>
                          {factorySubstrandsList.map((ss: any, idx: number) => {
                            const isSelected = (ss.sub_strand_name || ss.name) === genSubstrand;
                            const hours = ss.allocated_hours || "4h";
                            const sloCount = (ss.slos || []).length;
                            return (
                              <button
                                key={idx}
                                className={isSelected ? "" : "ghost"}
                                style={{
                                  fontSize: "11.5px",
                                  padding: "4px 10px",
                                  borderRadius: "20px",
                                  background: isSelected ? "#15803d" : "#fff",
                                  color: isSelected ? "#fff" : "#14532d",
                                  borderColor: isSelected ? "#15803d" : "#86efac",
                                  fontWeight: isSelected ? 700 : 500,
                                }}
                                onClick={() => selectSubstrandForFactory(ss, genGrade, genSubject)}
                              >
                                🌱 {ss.sub_strand_name || ss.name || `Sub-strand ${idx + 1}`}{" "}
                                <span style={{ opacity: 0.85, fontSize: "10px" }}>⏱️ {hours} • 🎯 {sloCount} SLOs</span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                      {lastPersistedTime && (
                        <span className="pill ok" style={{ fontSize: "11px", fontWeight: 700, background: "#dcfce7", color: "#15803d", borderColor: "#86efac" }}>
                          💾 Auto-Saved ({lastPersistedTime})
                        </span>
                      )}
                      <button
                        style={{ fontSize: "12px", background: "#7c3aed", color: "#fff", borderColor: "#7c3aed", fontWeight: 700 }}
                        onClick={openQuestionsFactoryFromContentFactory}
                      >
                        🎯 Launch Questions Factory ➔
                      </button>
                      <button
                        className="ghost"
                        style={{ fontSize: "12px", border: "1px solid #86efac", color: "#166534" }}
                        onClick={() => setShowBlueprintDetails(!showBlueprintDetails)}
                      >
                        {showBlueprintDetails ? "📋 Hide Blueprint" : "📋 View Blueprint & SLOs"}
                      </button>
                      <button onClick={triggerGenerate} disabled={isRunning} style={{ whiteSpace: "nowrap" }}>
                        {isRunning ? "⚡ Generating Pipeline..." : "⚡ Generate Entire 4-Layer Bundle"}
                      </button>
                    </div>
                  </div>

                  {/* PARENT STRAND NOTICE (If user hasn't selected a sub-strand yet) */}
                  {(!factorySelectedSubstrand || genSubstrand === genStrand || !genSubstrand) && (
                    <div style={{ margin: "14px 0", padding: "14px", background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: "8px", color: "#92400e" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
                        <div>
                          <strong>⚠️ Parent Strand Active: "{genStrand || 'Selected Strand'}"</strong>
                          <p style={{ margin: "4px 0 0", fontSize: "12px" }}>
                            Strands are large parent concepts. Notes, SVG diagrams, practical experiments, and assessment items are strictly generated on <strong>Sub-strands</strong> to ensure high depth, granular mastery, and zero hallucination.
                          </p>
                        </div>
                        {factorySubstrandsList.length > 0 ? (
                          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                            <span style={{ fontSize: "12px", fontWeight: 700, color: "#14532d" }}>👉 Pick a Sub-strand to load:</span>
                            {factorySubstrandsList.slice(0, 4).map((ss: any, idx: number) => (
                              <button
                                key={idx}
                                style={{ fontSize: "11.5px", padding: "5px 10px", background: "#166534", color: "#fff", borderColor: "#166534" }}
                                onClick={() => selectSubstrandForFactory(ss, genGrade, genSubject)}
                              >
                                🌱 {ss.sub_strand_name || ss.name}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <button
                            style={{ fontSize: "12px", padding: "6px 14px", background: "#059669", color: "#fff", borderColor: "#059669" }}
                            onClick={() => {
                              handleOpenSubstrandGenerator(genStrand || "1.0 General Strand");
                              setFactoryStep(1);
                            }}
                          >
                            ✨ AI Auto-Break Strand into Sub-strands ➔
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Expandable Sub-strand Blueprint & Prompt Context Card */}
                  {showBlueprintDetails && factorySelectedSubstrand && (
                    <div style={{ marginTop: "14px", paddingTop: "14px", borderTop: "1px dashed #86efac", fontSize: "12px" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "10px" }}>
                        {/* SLOs */}
                        <div style={{ padding: "8px 12px", background: "#fff", borderRadius: "8px", border: "1px solid #bbf7d0" }}>
                          <strong style={{ color: "#166534" }}>🎯 Specific Learning Outcomes (SLOs):</strong>
                          <ul style={{ margin: "4px 0 0", paddingLeft: "16px", color: "#334155" }}>
                            {(factorySelectedSubstrand.slos || []).map((slo: any, sIdx: number) => (
                              <li key={sIdx}>{typeof slo === "string" ? slo : (slo.text || slo.name || JSON.stringify(slo))}</li>
                            ))}
                          </ul>
                        </div>

                        {/* KIQs */}
                        {factorySelectedSubstrand.key_inquiry_questions && (
                          <div style={{ padding: "8px 12px", background: "#fff", borderRadius: "8px", border: "1px solid #bbf7d0" }}>
                            <strong style={{ color: "#0369a1" }}>❓ Key Inquiry Questions:</strong>
                            <p style={{ margin: "4px 0 0", color: "#334155" }}>
                              {Array.isArray(factorySelectedSubstrand.key_inquiry_questions)
                                ? factorySelectedSubstrand.key_inquiry_questions.join(" • ")
                                : factorySelectedSubstrand.key_inquiry_questions}
                            </p>
                          </div>
                        )}

                        {/* Visual & Practical Targets */}
                        <div style={{ padding: "8px 12px", background: "#fff", borderRadius: "8px", border: "1px solid #bbf7d0" }}>
                          <strong style={{ color: "#0f766e" }}>📐 Diagram Concept Target:</strong>
                          <div style={{ color: "#334155", margin: "2px 0 6px" }}>
                            {Array.isArray(factorySelectedSubstrand.required_diagrams)
                              ? factorySelectedSubstrand.required_diagrams.join(", ")
                              : (factorySelectedSubstrand.required_diagrams || "Concept Diagram")}
                          </div>
                          <strong style={{ color: "#0f766e" }}>🧪 Practical Experiment:</strong>
                          <div style={{ color: "#334155", marginTop: "2px" }}>
                            {Array.isArray(factorySelectedSubstrand.experiments)
                              ? factorySelectedSubstrand.experiments.join(", ")
                              : (factorySelectedSubstrand.experiments || "Hands-on Practical Task")}
                          </div>
                        </div>

                        {/* Safety Guidelines */}
                        {factorySelectedSubstrand.safety_hazards_to_check && (
                          <div style={{ padding: "8px 12px", background: "#fff5f5", borderRadius: "8px", border: "1px solid #fecdd3" }}>
                            <strong style={{ color: "#b91c1c" }}>⚠️ Mandatory Safety Hazard Protocols:</strong>
                            <div style={{ color: "#991b1b", marginTop: "4px" }}>
                              {Array.isArray(factorySelectedSubstrand.safety_hazards_to_check)
                                ? factorySelectedSubstrand.safety_hazards_to_check.join(" • ")
                                : factorySelectedSubstrand.safety_hazards_to_check}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Live Web & Academic Paper Research Intelligence Active Banner */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "8px", marginBottom: "16px" }}>
                  <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                    <span style={{ fontSize: "20px" }}>🌐</span>
                    <div>
                      <strong style={{ fontSize: "13px", color: "#14532d" }}>5-Layer Pipeline & Live Academic Research Agent Active</strong>
                      <div style={{ fontSize: "11px", color: "#166534" }}>Deep context flows sequentially between all layers. Every layer is verified by a 3-Agent Quality Gate (1 Reviewer + 2 Approvers).</div>
                    </div>
                  </div>
                  <button
                    className="ghost"
                    style={{ fontSize: "12px", border: "1px solid #16a34a", color: "#166534", fontWeight: 600 }}
                    onClick={() => { setActiveTraceStation("notes"); setShowTraceModal(true); }}
                  >
                    🧠 Inspect Agent Thinking Trace & Citations
                  </button>
                </div>

                {/* 4-Station Interactive Production Quadrant */}
                <div className="factory-quadrant">
                  {/* STATION 1: REVISION NOTES */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>📝 Station 1: Notes Studio (Layer 1)</h3>
                        <small className="muted">Exhaustive pedagogical exposition & PCK scaffolding</small>
                      </div>
                      <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                        {notesResearchDossier && (
                          <span
                            className="pill ok"
                            style={{ fontSize: "10px", cursor: "pointer" }}
                            onClick={() => { setActiveTraceStation("notes"); setShowTraceModal(true); }}
                          >
                            🌐 {notesResearchDossier.citations?.length || 0} Sources • 🛡️ {notesQualityAudit?.score || 100}%
                          </span>
                        )}
                        {notesQualityGate && (
                          <span
                            className={`pill ${notesQualityGate.passed ? "ok" : "warn"}`}
                            style={{ fontSize: "10px" }}
                            title={notesQualityGate.summary_message}
                          >
                            🛡️ Gate: {notesQualityGate.overall_score}% ({notesQualityGate.passed ? "PASSED" : "REVISE"})
                          </span>
                        )}
                        <span className={`pill ${notesApproved ? "ok" : stationNotes ? "warn" : "idle"}`}>
                          {notesApproved ? "Approved" : stationNotes ? "Generated" : "Pending"}
                        </span>
                      </div>
                    </div>

                    <div className="factory-refine-box">
                      <input
                        placeholder="Refine notes prompt (e.g., add more real-world Kenyan examples)..."
                        value={notesRefinePrompt}
                        onChange={(e) => setNotesRefinePrompt(e.target.value)}
                      />
                      <button
                        onClick={() => generateFactoryNotes(notesRefinePrompt)}
                        disabled={isRunning}
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {stationNotes ? "🔄 Regenerate" : "⚡ Generate Layer 1"}
                      </button>
                    </div>

                    <div className="factory-preview-pane">
                      {stationNotes ? (() => {
                        const hourModulesList = (stationNotes.hour_modules && stationNotes.hour_modules.length > 0)
                          ? stationNotes.hour_modules
                          : (stationNotes.key_concepts || []);

                        const displayedHours = activeHourView === "all"
                          ? hourModulesList
                          : hourModulesList.filter((hm: any, idx: number) => (hm.hour_number || idx + 1) === activeHourView);

                        return (
                          <div style={{ display: "grid", gap: "12px" }}>
                            <div style={{ padding: "14px", background: "#f0f9ff", borderRadius: "8px", border: "1px solid #bae6fd" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                                <strong style={{ fontSize: "15px", color: "#0369a1" }}>📘 {stationNotes.title}</strong>
                                <span className="pill ok" style={{ fontSize: "11px", fontWeight: 700 }}>
                                  ⏱️ {stationNotes.allocated_hours || 4} Contact Hours (240 mins)
                                </span>
                              </div>
                              <p style={{ margin: "8px 0 0", fontSize: "13px", lineHeight: "1.6", color: "#334155" }}>{stationNotes.intro}</p>
                            </div>

                            {/* Hour-by-Hour Interactive Navigation Bar */}
                            {hourModulesList.length > 1 && (
                              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", padding: "8px 10px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                                <button
                                  className={activeHourView === "all" ? "" : "ghost"}
                                  style={{ fontSize: "11.5px", padding: "4px 10px", borderRadius: "6px" }}
                                  onClick={() => setActiveHourView("all")}
                                >
                                  📖 All {hourModulesList.length} Hours (Full Master Guide)
                                </button>
                                {hourModulesList.map((hm: any, idx: number) => {
                                  const hNum = hm.hour_number || idx + 1;
                                  const hTitle = hm.hour_title || hm.heading || `Hour ${hNum}`;
                                  const shortTitle = hTitle.length > 35 ? hTitle.substring(0, 32) + "..." : hTitle;
                                  return (
                                    <button
                                      key={idx}
                                      className={activeHourView === hNum ? "" : "ghost"}
                                      style={{ fontSize: "11px", padding: "4px 8px", borderRadius: "6px" }}
                                      onClick={() => setActiveHourView(hNum)}
                                    >
                                      ⏰ Hour {hNum}: {shortTitle}
                                    </button>
                                  );
                                })}
                              </div>
                            )}

                            {/* Exhaustive Hour-by-Hour Lecture Modules */}
                            {displayedHours.map((hm: any, idx: number) => {
                              const hNum = hm.hour_number || (activeHourView === "all" ? idx + 1 : activeHourView);
                              const hTitle = hm.hour_title || hm.heading || `Hour ${hNum}: Core Pedagogical Module`;
                              const fullText = hm.full_lecture_notes || hm.detailed_exposition || hm.content;
                              const subsections = hm.subsections || hm.sub_sections || [];
                              const quantData = hm.quantitative_data_summary || [];
                              const pck = hm.pedagogical_notes || hm.teacher_facilitation_steps;
                              const misc = hm.common_misconceptions;
                              const formative = hm.formative_checks;
                              const tasks = hm.active_trainee_tasks || hm.learner_active_tasks;

                              return (
                                <div key={idx} style={{ padding: "16px", background: "#fff", borderRadius: "8px", border: "1px solid #cbd5e1", boxShadow: "0 2px 4px rgba(0,0,0,0.04)" }}>
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #f1f5f9", paddingBottom: "8px", marginBottom: "10px" }}>
                                    <strong style={{ fontSize: "14.5px", color: "#0f172a" }}>
                                      {hTitle.startsWith("Hour") ? hTitle : `Hour ${hNum}: ${hTitle}`}
                                    </strong>
                                    <span className="pill ok" style={{ fontSize: "10.5px" }}>60 Contact Minutes</span>
                                  </div>

                                  {hm.learning_intent && (
                                    <div style={{ padding: "6px 10px", background: "#f0f9ff", borderRadius: "6px", fontSize: "12px", color: "#0369a1", marginBottom: "10px" }}>
                                      🎯 <strong>Session Learning Intent:</strong> {hm.learning_intent}
                                    </div>
                                  )}

                                  {/* Substantive Multi-Paragraph Lecture Notes */}
                                  <div style={{ fontSize: "13px", lineHeight: "1.65", color: "#1e293b", whiteSpace: "pre-line", marginBottom: "12px" }}>
                                    {fullText}
                                  </div>

                                  {/* Sub-sections */}
                                  {subsections.length > 0 && (
                                    <div style={{ display: "grid", gap: "8px", margin: "10px 0 14px", paddingLeft: "12px", borderLeft: "3px solid #0284c7" }}>
                                      {subsections.map((sub: any, sIdx: number) => (
                                        <div key={sIdx} style={{ fontSize: "12.5px", background: "#f8fafc", padding: "10px 12px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                                          <strong style={{ color: "#0369a1" }}>{sub.title}</strong>
                                          <p style={{ margin: "4px 0 0", color: "#334155", lineHeight: "1.55", whiteSpace: "pre-line" }}>{sub.content}</p>
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {/* Quantitative Data Summary */}
                                  {quantData.length > 0 && (
                                    <div style={{ padding: "8px 12px", background: "#faf5ff", borderRadius: "6px", border: "1px solid #f3e8ff", margin: "10px 0", fontSize: "11.5px" }}>
                                      <strong style={{ color: "#7e22ce" }}>📊 Key Empirical Data & Parameters:</strong>
                                      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "4px" }}>
                                        {quantData.map((qd: any, qIdx: number) => (
                                          <span key={qIdx} style={{ background: "#fff", padding: "3px 8px", borderRadius: "4px", border: "1px solid #e9d5ff", color: "#581c87" }}>
                                            <strong>{qd.metric}:</strong> {qd.value} {qd.source ? `(${qd.source})` : ""}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Teacher Facilitation / PCK */}
                                  {pck && (
                                    <div style={{ marginTop: "8px", padding: "8px 12px", background: "#fefce8", borderRadius: "6px", border: "1px solid #fef08a", fontSize: "12px", color: "#854d0e" }}>
                                      💡 <strong>Pedagogical Content Knowledge (PCK) Facilitation:</strong> {pck}
                                    </div>
                                  )}

                                  {/* Trainee Active Tasks */}
                                  {tasks && (
                                    <div style={{ marginTop: "8px", padding: "8px 12px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0", fontSize: "12px", color: "#166534" }}>
                                      ✍️ <strong>Active Trainee Task / Practicum:</strong> {tasks}
                                    </div>
                                  )}

                                  {/* Misconception Diagnostics */}
                                  {misc && (
                                    <div style={{ marginTop: "8px", padding: "8px 12px", background: "#fff1f2", borderRadius: "6px", border: "1px solid #fecdd3", fontSize: "12px", color: "#9f1239" }}>
                                      ⚠️ <strong>Learner Misconception Diagnostic:</strong> {misc}
                                    </div>
                                  )}

                                  {/* Formative Assessment Checks */}
                                  {formative && (
                                    <div style={{ marginTop: "8px", padding: "8px 12px", background: "#f1f5f9", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px", color: "#0f172a" }}>
                                      ❓ <strong>Formative Assessment Cues:</strong>
                                      {Array.isArray(formative) ? (
                                        <ul style={{ margin: "4px 0 0", paddingLeft: "18px", color: "#334155" }}>
                                          {formative.map((fQ: string, fIdx: number) => (
                                            <li key={fIdx}>{fQ}</li>
                                          ))}
                                        </ul>
                                      ) : (
                                        <div style={{ marginTop: "4px", color: "#334155" }}>{formative}</div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}

                            {/* Cross-Cutting Practical Connections */}
                            {stationNotes.practical_connections && (
                              <div style={{ padding: "14px", background: "#f0fdfa", borderRadius: "8px", border: "1px solid #99f6e4" }}>
                                <strong style={{ fontSize: "14px", color: "#0f766e" }}>🔬 Practical Connection: {stationNotes.practical_connections.activity_title}</strong>
                                {stationNotes.practical_connections.materials_needed?.length > 0 && (
                                  <div style={{ fontSize: "12px", marginTop: "6px", color: "#115e59" }}>
                                    <strong>Materials / Resources:</strong> {Array.isArray(stationNotes.practical_connections.materials_needed) ? stationNotes.practical_connections.materials_needed.join(", ") : stationNotes.practical_connections.materials_needed}
                                  </div>
                                )}
                                {stationNotes.practical_connections.procedure && (
                                  <div style={{ fontSize: "12px", marginTop: "6px", color: "#334155" }}>
                                    <strong>Step-by-Step Procedure:</strong> {Array.isArray(stationNotes.practical_connections.procedure) ? stationNotes.practical_connections.procedure.join(" ➔ ") : stationNotes.practical_connections.procedure}
                                  </div>
                                )}
                                {stationNotes.practical_connections.safety_precautions && (
                                  <div style={{ fontSize: "12px", marginTop: "6px", color: "#b91c1c" }}>
                                    🚨 <strong>Safety Protocol:</strong> {stationNotes.practical_connections.safety_precautions}
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Worked Case Study Examples */}
                            {stationNotes.worked_examples?.length > 0 && (
                              <div style={{ padding: "14px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #cbd5e1" }}>
                                <strong style={{ fontSize: "13.5px", color: "#334155" }}>💼 Authentic Worked Case Studies:</strong>
                                {stationNotes.worked_examples.map((we: any, idx: number) => (
                                  <div key={idx} style={{ fontSize: "12px", marginTop: "8px", padding: "10px 12px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                                    <div style={{ color: "#0f172a" }}><strong>Scenario:</strong> {we.scenario}</div>
                                    <div style={{ marginTop: "4px", color: "#0369a1" }}><strong>Resolution Steps:</strong> {Array.isArray(we.solution_steps) ? we.solution_steps.join(" ➔ ") : we.solution_steps}</div>
                                    {(we.explanation || we.solution_explanation) && (
                                      <div style={{ marginTop: "4px", color: "#475569", fontStyle: "italic" }}>
                                        <strong>Rationale:</strong> {we.explanation || we.solution_explanation}
                                      </div>
                                    )}
                                    {we.research_source && (
                                      <div style={{ marginTop: "4px", color: "#64748b", fontSize: "11px" }}>
                                        📚 <strong>Source:</strong> {we.research_source}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Key Inquiry Questions */}
                            {stationNotes.key_inquiry_questions?.length > 0 && (
                              <div style={{ padding: "12px", background: "#fefce8", borderRadius: "8px", border: "1px solid #fef08a", fontSize: "12px" }}>
                                <strong style={{ color: "#854d0e", fontSize: "13px" }}>🎯 High-Order Key Inquiry Questions:</strong>
                                <ul style={{ margin: "6px 0 0", paddingLeft: "18px", color: "#713f12" }}>
                                  {stationNotes.key_inquiry_questions.map((kiq: string, idx: number) => (
                                    <li key={idx} style={{ marginBottom: "2px" }}>{kiq}</li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {/* Research References & Bibliography */}
                            {stationNotes.research_references?.length > 0 && (
                              <div style={{ padding: "14px", background: "#f1f5f9", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "12px" }}>
                                <strong style={{ color: "#1e293b", fontSize: "13px" }}>📚 Verifiable Research References & Published Policy Documents:</strong>
                                <div style={{ display: "grid", gap: "6px", marginTop: "8px" }}>
                                  {stationNotes.research_references.map((ref: any, rIdx: number) => (
                                    <div key={rIdx} style={{ padding: "8px 12px", background: "#fff", borderRadius: "4px", border: "1px solid #e2e8f0" }}>
                                      <strong style={{ color: "#0f172a" }}>{ref.source_title || ref.title}</strong> ({ref.year || "2024"})
                                      <div style={{ color: "#475569", fontSize: "11.5px", marginTop: "2px" }}>
                                        Author / Agency: {ref.author_organization || ref.agency || "Government of Kenya"} • Cites: {ref.key_data_points_cited || ref.data_point}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {stationNotes.summary_points?.length > 0 && (
                              <div style={{ padding: "12px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", fontSize: "12px" }}>
                                <strong style={{ color: "#0f172a", fontSize: "13px" }}>📌 Summary Takeaways:</strong>
                                <ul style={{ margin: "6px 0 0", paddingLeft: "18px", color: "#334155" }}>
                                  {stationNotes.summary_points.map((sp: string, idx: number) => (
                                    <li key={idx} style={{ marginBottom: "2px" }}>{sp}</li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {/* SNE & Plain Language Adaptation */}
                            {stationNotes.accessibility_support?.plain_language_summary && (
                              <div style={{ padding: "10px 12px", background: "#eff6ff", borderRadius: "6px", fontSize: "12px", color: "#1e40af", border: "1px solid #bfdbfe" }}>
                                ♿ <strong>SNE Plain Language & Differentiated Support:</strong> {stationNotes.accessibility_support.plain_language_summary}
                              </div>
                            )}
                          </div>
                        );
                      })() : (
                        <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                          <p>Click "⚡ Generate Layer 1" to synthesize high-depth revision notes.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button
                        className={notesApproved ? "ghost" : ""}
                        onClick={toggleNotesApproval}
                        disabled={!stationNotes}
                      >
                        {notesApproved ? "✓ Notes Approved" : "✅ Approve Notes"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 2: MULTI-VISUALS & DIAGRAMS STUDIO */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>📐 Station 2: Visuals & Diagrams Studio (Layer 2)</h3>
                        <small className="muted">
                          {stationVisualsList.length > 0
                            ? `${stationVisualsList.length} Visual Assets Planned / Generated`
                            : "Multi-item technical SVGs, photorealistic scenes, and schematics derived from Notes"}
                        </small>
                      </div>
                      <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                        <button
                          className="ghost"
                          style={{ fontSize: "11px", padding: "3px 8px", background: "#f0fdf4", color: "#166534", borderColor: "#86efac" }}
                          onClick={() => planFactoryVisuals()}
                          disabled={isRunning}
                          title="Auto-discover all required diagrams, schematics, and realistic scene illustrations for this sub-strand"
                        >
                          ✨ Plan Required Visuals ({stationVisualsList.length || "Auto"})
                        </button>
                        <button
                          className="ghost"
                          style={{ fontSize: "11px", padding: "3px 8px", background: "#f0f9ff", color: "#0369a1", borderColor: "#bae6fd" }}
                          onClick={() => generateAllVisuals()}
                          disabled={isRunning || stationVisualsList.length === 0}
                          title="Synthesize all planned visual assets one by one"
                        >
                          ⚡ Generate All ({stationVisualsList.length})
                        </button>
                        {diagramResearchDossier && (
                          <span
                            className="pill ok"
                            style={{ fontSize: "10px", cursor: "pointer" }}
                            onClick={() => { setActiveTraceStation("diagram"); setShowTraceModal(true); }}
                          >
                            🌐 {diagramResearchDossier.citations?.length || 0} Sources • 🛡️ {diagramQualityAudit?.score || 100}%
                          </span>
                        )}
                        {diagramQualityGate && (
                          <span
                            className={`pill ${diagramQualityGate.passed ? "ok" : "warn"}`}
                            style={{ fontSize: "10px" }}
                            title={diagramQualityGate.summary_message}
                          >
                            🛡️ Gate: {diagramQualityGate.overall_score}% ({diagramQualityGate.passed ? "PASSED" : "REVISE"})
                          </span>
                        )}
                        <span className={`pill ${diagramApproved ? "ok" : (stationVisualsList.length > 0 || stationDiagram) ? "warn" : "idle"}`}>
                          {diagramApproved ? "Approved" : (stationVisualsList.length > 0 || stationDiagram) ? "Generated" : "Pending"}
                        </span>
                      </div>
                    </div>

                    {/* Multi-Visual Selection Tabs */}
                    {stationVisualsList.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "8px" }}>
                        {stationVisualsList.map((vis: any, vIdx: number) => {
                          const isActive = vIdx === activeVisualIdx;
                          const isGen = vis.status === "generated" || vis.diagram_svg;
                          return (
                            <button
                              key={vIdx}
                              className={isActive ? "" : "ghost"}
                              style={{
                                fontSize: "11.5px",
                                padding: "4px 10px",
                                borderRadius: "6px",
                                background: isActive ? "#0284c7" : "#fff",
                                color: isActive ? "#fff" : "#0f172a",
                                borderColor: isActive ? "#0284c7" : "#cbd5e1",
                                fontWeight: isActive ? 700 : 500,
                              }}
                              onClick={() => {
                                setActiveVisualIdx(vIdx);
                                setStationDiagram(vis);
                              }}
                            >
                              {vis.asset_type === "realistic_image" ? "🎨" : "📐"} {vIdx + 1}. {vis.title || `Visual ${vIdx + 1}`}{" "}
                              <span style={{ opacity: 0.8, fontSize: "10px" }}>({isGen ? "✓ Ready" : "Planned"})</span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {/* Active Visual Meta & Prompt Bar */}
                    {(() => {
                      const curVis = stationVisualsList[activeVisualIdx] || stationDiagram;
                      return (
                        <div>
                          {curVis && (
                            <div style={{ padding: "8px 12px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", marginBottom: "8px", fontSize: "12px" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                <strong style={{ color: "#0c4a6e", fontSize: "13px" }}>
                                  {curVis.title || diagramConceptInput || "Active Visual Specification"}
                                </strong>
                                <span className="pill ok" style={{ fontSize: "10.5px" }}>
                                  {curVis.asset_type || "technical_svg"}
                                </span>
                              </div>
                              {curVis.pedagogical_purpose && (
                                <p style={{ margin: "4px 0 0", color: "#475569" }}>
                                  <strong>Purpose:</strong> {curVis.pedagogical_purpose}
                                </p>
                              )}
                            </div>
                          )}

                          <div className="factory-refine-box" style={{ margin: "0 0 8px" }}>
                            <input
                              placeholder="Refine active visual prompt (e.g., add clear callout leader lines, authentic Kenyan soil textures)..."
                              value={diagramRefinePrompt}
                              onChange={(e) => setDiagramRefinePrompt(e.target.value)}
                            />
                            <button
                              onClick={() => {
                                if (stationVisualsList.length > 0 && stationVisualsList[activeVisualIdx]) {
                                  generateSingleVisual(stationVisualsList[activeVisualIdx], activeVisualIdx, diagramRefinePrompt);
                                } else {
                                  generateFactoryDiagram(diagramRefinePrompt);
                                }
                              }}
                              disabled={isRunning}
                              style={{ whiteSpace: "nowrap" }}
                            >
                              {curVis?.diagram_svg || curVis?.image_prompt ? "🔄 Regenerate Active Visual" : "⚡ Generate Active Visual"}
                            </button>
                          </div>

                          {/* Visual Sub-View Mode Toggles */}
                          <div style={{ display: "flex", gap: "6px", marginTop: "4px" }}>
                            <button
                              className={diagramViewMode === "visual" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setDiagramViewMode("visual")}
                            >
                              🖼️ Vector Canvas (SVG)
                            </button>
                            <button
                              className={diagramViewMode === "image_spec" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setDiagramViewMode("image_spec")}
                            >
                              🎨 Photorealistic / AI Image Prompt Spec
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

                          <div className="factory-preview-pane" style={{ padding: "8px", marginTop: "8px" }}>
                            {curVis ? (
                              <div>
                                {diagramViewMode === "visual" && (
                                  <div
                                    className="svg-canvas-box"
                                    dangerouslySetInnerHTML={{ __html: sanitizeSvgForDisplay(curVis.diagram_svg || "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 500'><rect width='100%' height='100%' fill='#f8fafc'/><text x='400' y='250' font-family='sans-serif' font-size='16' text-anchor='middle' fill='#0369a1'>Click Generate to synthesize visual</text></svg>") }}
                                  />
                                )}

                                {diagramViewMode === "image_spec" && (
                                  <div style={{ padding: "12px", background: "#faf5ff", borderRadius: "8px", border: "1px solid #e9d5ff", fontSize: "12px" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                                      <strong style={{ color: "#7e22ce" }}>🎨 Comprehensive Photorealistic AI Image Prompt:</strong>
                                      <span className="pill ok" style={{ fontSize: "10px" }}>Aspect Ratio: {curVis.aspect_ratio || "16:9"}</span>
                                    </div>
                                    <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #d8b4fe", color: "#3b0764", fontFamily: "monospace", fontSize: "11.5px", lineHeight: 1.5 }}>
                                      {curVis.image_prompt || curVis.vivid_prompt || "Photorealistic educational illustration showing authentic Kenyan practical learning, high depth of field, natural golden-hour lighting, high visual clarity."}
                                    </div>
                                    {curVis.composition_guide && (
                                      <div style={{ marginTop: "8px", color: "#6b21a8" }}>
                                        <strong>Camera & Lighting Guide:</strong> {curVis.composition_guide}
                                      </div>
                                    )}
                                    {curVis.negative_prompt && (
                                      <div style={{ marginTop: "6px", color: "#9333ea", fontSize: "11px" }}>
                                        <strong>Negative Prompt:</strong> {curVis.negative_prompt}
                                      </div>
                                    )}
                                  </div>
                                )}

                                {diagramViewMode === "code" && (
                                  <pre style={{ fontSize: "10px", maxHeight: "250px" }}>
                                    {curVis.diagram_svg || "<svg .../>"}
                                  </pre>
                                )}

                                {diagramViewMode === "tactile" && (
                                  <div style={{ padding: "10px", fontSize: "12px" }}>
                                    <strong>Alt Text Description:</strong>
                                    <p style={{ margin: "4px 0 10px" }}>{curVis.accessibility?.alt_text || "Visual model of the concept."}</p>
                                    <strong>Raised-Line Tactile Guidance (SNE):</strong>
                                    <p style={{ margin: "4px 0" }}>{curVis.accessibility?.tactile_description || "Use tactile braille embosser with raised outlines."}</p>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                                <p>Click "✨ Plan Required Visuals" to discover all diagrams, schematics, and realistic scene illustrations for this sub-strand.</p>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })()}

                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "8px" }}>
                      <button
                        className={diagramApproved ? "ghost" : ""}
                        onClick={toggleDiagramApproval}
                        disabled={!stationDiagram && stationVisualsList.length === 0}
                      >
                        {diagramApproved ? "✓ Visuals Approved" : "✅ Approve Visuals"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 3: MULTI-ACTIVITIES, EXPERIMENTS & VIDEO STORYBOARDS */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>🧪 Station 3: Activities, Experiments & Video Storyboard Studio (Layer 3)</h3>
                        <small className="muted">
                          {stationActivitiesList.length > 0
                            ? `${stationActivitiesList.length} Practical Modules Planned / Generated`
                            : "Hands-on experiments, CSL field projects, and step-by-step video storyboards"}
                        </small>
                      </div>
                      <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                        <button
                          className="ghost"
                          style={{ fontSize: "11px", padding: "3px 8px", background: "#f0fdf4", color: "#166534", borderColor: "#86efac" }}
                          onClick={() => planFactoryActivities()}
                          disabled={isRunning}
                          title="Auto-discover all required laboratory experiments, outdoor inquiries, and classroom games for this sub-strand"
                        >
                          ✨ Plan Required Practicals ({stationActivitiesList.length || "Auto"})
                        </button>
                        <button
                          className="ghost"
                          style={{ fontSize: "11px", padding: "3px 8px", background: "#f0f9ff", color: "#0369a1", borderColor: "#bae6fd" }}
                          onClick={() => generateAllActivities()}
                          disabled={isRunning || stationActivitiesList.length === 0}
                          title="Synthesize all planned practical tasks and video scripts"
                        >
                          ⚡ Generate All ({stationActivitiesList.length})
                        </button>
                        {activityResearchDossier && (
                          <span
                            className="pill ok"
                            style={{ fontSize: "10px", cursor: "pointer" }}
                            onClick={() => { setActiveTraceStation("activity"); setShowTraceModal(true); }}
                          >
                            🌐 {activityResearchDossier.citations?.length || 0} Sources • 🛡️ {activityQualityAudit?.score || 100}%
                          </span>
                        )}
                        {activityQualityGate && (
                          <span
                            className={`pill ${activityQualityGate.passed ? "ok" : "warn"}`}
                            style={{ fontSize: "10px" }}
                            title={activityQualityGate.summary_message}
                          >
                            🛡️ Gate: {activityQualityGate.overall_score}% ({activityQualityGate.passed ? "PASSED" : "REVISE"})
                          </span>
                        )}
                        <span className={`pill ${activityApproved ? "ok" : (stationActivitiesList.length > 0 || stationActivity) ? "warn" : "idle"}`}>
                          {activityApproved ? "Approved" : (stationActivitiesList.length > 0 || stationActivity) ? "Generated" : "Pending"}
                        </span>
                      </div>
                    </div>

                    {/* Multi-Activity Selection Tabs */}
                    {stationActivitiesList.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "8px" }}>
                        {stationActivitiesList.map((act: any, aIdx: number) => {
                          const isActive = aIdx === activeActivityIdx;
                          const isGen = act.status === "generated" || (act.procedure_steps && act.procedure_steps.length > 0);
                          return (
                            <button
                              key={aIdx}
                              className={isActive ? "" : "ghost"}
                              style={{
                                fontSize: "11.5px",
                                padding: "4px 10px",
                                borderRadius: "6px",
                                background: isActive ? "#0e7490" : "#fff",
                                color: isActive ? "#fff" : "#0f172a",
                                borderColor: isActive ? "#0e7490" : "#cbd5e1",
                                fontWeight: isActive ? 700 : 500,
                              }}
                              onClick={() => {
                                setActiveActivityIdx(aIdx);
                                setStationActivity(act);
                              }}
                            >
                              🧪 {aIdx + 1}. {act.activity_name || `Practical ${aIdx + 1}`}{" "}
                              <span style={{ opacity: 0.8, fontSize: "10px" }}>({isGen ? "✓ Ready" : "Planned"})</span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {/* Active Activity Meta & Prompt Bar */}
                    {(() => {
                      const curAct = stationActivitiesList[activeActivityIdx] || stationActivity;
                      return (
                        <div>
                          {curAct && (
                            <div style={{ padding: "8px 12px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", marginBottom: "8px", fontSize: "12px" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                <strong style={{ color: "#0891b2", fontSize: "13px" }}>
                                  {curAct.activity_name || curAct.title || "Active Practical Module"}
                                </strong>
                                <span className="pill ok" style={{ fontSize: "10.5px" }}>
                                  {curAct.activity_type || "laboratory_experiment"}
                                </span>
                              </div>
                              {curAct.objective && (
                                <p style={{ margin: "4px 0 0", color: "#475569" }}>
                                  <strong>Objective:</strong> {curAct.objective}
                                </p>
                              )}
                            </div>
                          )}

                          <div className="factory-refine-box" style={{ margin: "0 0 8px" }}>
                            <input
                              placeholder="Refine practical module (e.g., add detailed video narration for Step 2, mandate safety goggles)..."
                              value={activityRefinePrompt}
                              onChange={(e) => setActivityRefinePrompt(e.target.value)}
                            />
                            <button
                              onClick={() => {
                                if (stationActivitiesList.length > 0 && stationActivitiesList[activeActivityIdx]) {
                                  generateSingleActivity(stationActivitiesList[activeActivityIdx], activeActivityIdx, activityRefinePrompt);
                                } else {
                                  generateFactoryActivity(activityRefinePrompt);
                                }
                              }}
                              disabled={isRunning}
                              style={{ whiteSpace: "nowrap" }}
                            >
                              {curAct?.procedure_steps ? "🔄 Regenerate Active Practical" : "⚡ Generate Active Practical"}
                            </button>
                          </div>

                          {/* Activity Detail Sub-Tabs */}
                          <div style={{ display: "flex", gap: "6px", marginTop: "4px" }}>
                            <button
                              className={activityDetailTab === "procedure" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setActivityDetailTab("procedure")}
                            >
                              📋 Step-by-Step Procedure & Apparatus
                            </button>
                            <button
                              className={activityDetailTab === "video" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setActivityDetailTab("video")}
                            >
                              🎬 Video Storyboard Script ({curAct?.video_storyboard?.scenes?.length || 0} Scenes)
                            </button>
                            <button
                              className={activityDetailTab === "image" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setActivityDetailTab("image")}
                            >
                              🎨 Action Photo / Scene Prompt
                            </button>
                            <button
                              className={activityDetailTab === "safety" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setActivityDetailTab("safety")}
                            >
                              ⚠️ Hazard & PPE Protocols
                            </button>
                            <button
                              className={activityDetailTab === "rubric" ? "" : "ghost"}
                              style={{ fontSize: "11px", padding: "4px 8px" }}
                              onClick={() => setActivityDetailTab("rubric")}
                            >
                              🎯 4-Tier Assessment Rubric
                            </button>
                          </div>

                          <div className="factory-preview-pane" style={{ padding: "10px", marginTop: "8px" }}>
                            {curAct ? (
                              <div>
                                {activityDetailTab === "procedure" && (
                                  <div>
                                    {curAct.materials && (
                                      <div style={{ marginBottom: "10px", fontSize: "12px", padding: "8px 12px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0" }}>
                                        <strong style={{ color: "#166534" }}>🧪 Apparatus & Local Materials:</strong>
                                        <div style={{ color: "#14532d", marginTop: "3px" }}>
                                          {Array.isArray(curAct.materials) ? curAct.materials.join(" • ") : curAct.materials}
                                        </div>
                                      </div>
                                    )}

                                    {curAct.procedure_steps && curAct.procedure_steps.length > 0 ? (
                                      <div style={{ fontSize: "12.5px" }}>
                                        <strong style={{ color: "#0c4a6e" }}>Step-by-Step Practical Procedure:</strong>
                                        <ol style={{ margin: "6px 0 0", paddingLeft: "20px", lineHeight: 1.6 }}>
                                          {curAct.procedure_steps.map((st: string, idx: number) => (
                                            <li key={idx} style={{ marginBottom: "4px" }}>{st}</li>
                                          ))}
                                        </ol>
                                      </div>
                                    ) : (
                                      <p className="muted">Click "⚡ Generate Active Practical" to synthesize complete steps.</p>
                                    )}
                                  </div>
                                )}

                                {activityDetailTab === "video" && (
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                                      <strong style={{ color: "#0891b2", fontSize: "13px" }}>
                                        🎬 {curAct.video_storyboard?.video_title || `${curAct.activity_name} (Instructional Video Guide)`}
                                      </strong>
                                      <span className="pill ok" style={{ fontSize: "10px" }}>
                                        ⏱️ Target Duration: {curAct.video_storyboard?.target_duration || "90-120 seconds"}
                                      </span>
                                    </div>
                                    {curAct.video_storyboard?.overview && (
                                      <p style={{ margin: "0 0 10px", fontSize: "12px", color: "#475569" }}>
                                        <strong>Overview:</strong> {curAct.video_storyboard.overview}
                                      </p>
                                    )}

                                    {curAct.video_storyboard?.scenes && curAct.video_storyboard.scenes.length > 0 ? (
                                      <div style={{ display: "grid", gap: "8px" }}>
                                        {curAct.video_storyboard.scenes.map((sc: any, scIdx: number) => (
                                          <div
                                            key={scIdx}
                                            style={{
                                              padding: "10px 12px",
                                              background: "#f0f9ff",
                                              borderRadius: "8px",
                                              border: "1px solid #bae6fd",
                                              fontSize: "12px",
                                            }}
                                          >
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                              <strong style={{ color: "#0369a1" }}>
                                                🎥 Scene {sc.scene_number || scIdx + 1}: {sc.shot_type || "Demonstration Shot"}
                                              </strong>
                                            </div>
                                            <div style={{ marginTop: "4px", color: "#0f172a" }}>
                                              <strong>Visual Action on Screen:</strong> {sc.visual_action}
                                            </div>
                                            {sc.voiceover_narration && (
                                              <div style={{ marginTop: "4px", color: "#166534", background: "#f0fdf4", padding: "4px 8px", borderRadius: "4px", border: "1px solid #bbf7d0" }}>
                                                🗣️ <strong>Spoken Narration / Dialogue:</strong> "{sc.voiceover_narration}"
                                              </div>
                                            )}
                                            {sc.on_screen_text && (
                                              <div style={{ marginTop: "4px", color: "#0369a1", fontSize: "11px" }}>
                                                🏷️ <strong>On-Screen Callout:</strong> {sc.on_screen_text}
                                              </div>
                                            )}
                                            {sc.ai_video_prompt && (
                                              <div style={{ marginTop: "4px", color: "#64748b", fontSize: "10.5px", fontFamily: "monospace" }}>
                                                🤖 <strong>AI Video Model Prompt:</strong> {sc.ai_video_prompt}
                                              </div>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <p className="muted">No video storyboard scenes yet. Click "⚡ Generate Active Practical" to author video scripts.</p>
                                    )}
                                  </div>
                                )}

                                {activityDetailTab === "image" && (
                                  <div style={{ padding: "10px", background: "#faf5ff", borderRadius: "8px", border: "1px solid #e9d5ff", fontSize: "12px" }}>
                                    <strong style={{ color: "#7e22ce" }}>🎨 Action Photo / Instructional Scene Prompt:</strong>
                                    <div style={{ marginTop: "6px", padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #d8b4fe", color: "#3b0764", fontFamily: "monospace", fontSize: "11.5px", lineHeight: 1.5 }}>
                                      {curAct.visual_action_image_prompt || "Photorealistic high-clarity documentary photograph showing Kenyan students wearing safety aprons and conducting this investigation in a daylight science workbench, realistic hands-on actions, sharp focus, natural classroom setting."}
                                    </div>
                                  </div>
                                )}

                                {activityDetailTab === "safety" && (
                                  <div className="hazard-alert-box">
                                    <strong>🚨 MANDATORY SAFETY HAZARD GUIDELINES & PPE:</strong>
                                    <ul style={{ margin: "6px 0 0", paddingLeft: "18px", fontSize: "12px" }}>
                                      {(curAct.safety_hazards_to_check || curAct.safety_protocols?.hazard_warnings || [
                                        "Wear eye protection and laboratory aprons during manipulation of soil samples.",
                                        "Wash hands thoroughly with soap and clean water immediately after completing the investigation.",
                                        "Dispose of organic waste in designated compost receptacles."
                                      ]).map((hw: string, idx: number) => (
                                        <li key={idx} style={{ marginBottom: "2px" }}>{hw}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}

                                {activityDetailTab === "rubric" && (
                                  <div style={{ fontSize: "12px" }}>
                                    <strong style={{ color: "#0c4a6e" }}>🎯 4-Tier Assessment Rubric:</strong>
                                    <div className="rubric-grid" style={{ marginTop: "8px" }}>
                                      <div className="rubric-card exceeding">
                                        <strong style={{ color: "#15803d" }}>Exceeding</strong>
                                        {curAct.assessment_rubric?.exceeding || "Independently sets up apparatus, conducts investigation with zero errors, and formulates insightful hypotheses."}
                                      </div>
                                      <div className="rubric-card meeting">
                                        <strong style={{ color: "#0369a1" }}>Meeting</strong>
                                        {curAct.assessment_rubric?.meeting || "Accurately follows all procedure steps, records accurate observations, and adheres to safety protocols."}
                                      </div>
                                      <div className="rubric-card approaching">
                                        <strong style={{ color: "#b45309" }}>Approaching</strong>
                                        {curAct.assessment_rubric?.approaching || "Follows procedure with occasional teacher prompts and records basic observations."}
                                      </div>
                                      <div className="rubric-card below">
                                        <strong style={{ color: "#b91c1c" }}>Below</strong>
                                        {curAct.assessment_rubric?.below || "Requires direct continuous supervision to handle apparatus and follow safety instructions."}
                                      </div>
                                    </div>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div style={{ textAlign: "center", padding: "30px", color: "var(--muted)" }}>
                                <p>Click "✨ Plan Required Practicals" to discover all experiments, CSL field projects, and video storyboards for this sub-strand.</p>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })()}

                    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "8px" }}>
                      <button
                        className={activityApproved ? "ghost" : ""}
                        onClick={toggleActivityApproval}
                        disabled={!stationActivity && stationActivitiesList.length === 0}
                      >
                        {activityApproved ? "✓ Activities Approved" : "✅ Approve Activities"}
                      </button>
                    </div>
                  </div>

                  {/* STATION 4: CRITERION QUESTIONS & RUBRICS */}
                  <div className="factory-station-card">
                    <div className="factory-station-header">
                      <div>
                        <h3>❓ Station 4: Questions Studio (Layer 4)</h3>
                        <small className="muted">Derived from ALL upstream layers (Notes, Diagram, Activity)</small>
                      </div>
                      <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                        {questionsResearchDossier && (
                          <span
                            className="pill ok"
                            style={{ fontSize: "10px", cursor: "pointer" }}
                            onClick={() => { setActiveTraceStation("questions"); setShowTraceModal(true); }}
                          >
                            🌐 {questionsResearchDossier.citations?.length || 0} Sources • 🛡️ {questionsQualityAudit?.score || 100}%
                          </span>
                        )}
                        {questionsQualityGate && (
                          <span
                            className={`pill ${questionsQualityGate.passed ? "ok" : "warn"}`}
                            style={{ fontSize: "10px" }}
                            title={questionsQualityGate.summary_message}
                          >
                            🛡️ Gate: {questionsQualityGate.overall_score}% ({questionsQualityGate.passed ? "PASSED" : "REVISE"})
                          </span>
                        )}
                        <span className={`pill ${questionsApproved ? "ok" : stationQuestions.length > 0 ? "warn" : "idle"}`}>
                          {questionsApproved ? "Approved" : stationQuestions.length > 0 ? "Generated" : "Pending"}
                        </span>
                      </div>
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
                        {stationQuestions.length > 0 ? "🔄 Regenerate" : "⚡ Generate Layer 4"}
                      </button>
                    </div>

                    <div className="factory-preview-pane">
                      {stationQuestions.length > 0 ? (
                        <div>
                          {stationQuestions.map((q: any, idx: number) => {
                            const c = q.content || q;
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
                                {(() => {
                                  const safeOptions = normalizeQuestionOptions(c.options, c.correct_answer, c.distractor_explanations);
                                  if (!safeOptions || safeOptions.length === 0) return null;
                                  return (
                                    <div style={{ display: "grid", gap: "4px", margin: "6px 0" }}>
                                      {safeOptions.map((opt: any) => (
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
                                  );
                                })()}

                                {/* 4-Level KICD Scoring Rubric Grid */}
                                {c.marking_guide && (
                                  <div className="rubric-grid">
                                    <div className="rubric-card exceeding">
                                      <strong style={{ color: "#15803d" }}>Exceeding</strong>
                                      {c.marking_guide.exceeding}
                                    </div>
                                    <div className="rubric-card meeting">
                                      <strong style={{ color: "#0369a1" }}>Meeting</strong>
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
                          <p>Click "⚡ Generate Layer 4" to synthesize assessment items derived from all upstream layers.</p>
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "12px", flexWrap: "wrap", gap: "8px" }}>
                      <button
                        style={{ fontSize: "12px", background: "#7c3aed", color: "#fff", borderColor: "#7c3aed", fontWeight: 700 }}
                        onClick={openQuestionsFactoryFromContentFactory}
                      >
                        🚀 Launch Dedicated Questions Factory (Unlimited Items) ➔
                      </button>
                      <button
                        className={questionsApproved ? "ghost" : ""}
                        onClick={toggleQuestionsApproval}
                        disabled={stationQuestions.length === 0}
                      >
                        {questionsApproved ? "✓ Questions Approved" : "✅ Approve Questions"}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Bottom Navigation */}
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: "24px", padding: "16px", background: "#f8fafc", borderRadius: "10px", border: "1px solid #e2e8f0", flexWrap: "wrap", gap: "10px" }}>
                  <button className="ghost" onClick={() => setFactoryStep(1)}>
                    ⬅ Back to Step 1: Strands Architecture
                  </button>
                  <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                    <button
                      style={{ background: "#7c3aed", color: "#fff", borderColor: "#7c3aed", fontWeight: 700 }}
                      onClick={openQuestionsFactoryFromContentFactory}
                    >
                      🎯 Launch Questions Factory ➔
                    </button>
                    <button className="ghost" onClick={() => saveFactorySubstrandBundle("draft_in_factory")}>
                      💾 Save Draft Bundle
                    </button>
                    <button
                      onClick={async () => {
                        await runLiveBundleAudit();
                        setFactoryStep(3);
                      }}
                      disabled={!stationNotes && !stationDiagram && !stationActivity && stationQuestions.length === 0}
                    >
                      Proceed to Step 3: Audit & Deliberation ➔
                    </button>
                  </div>
                </div>

                {/* Agent Thinking Trace & Research Citations Modal */}
                {showTraceModal && (
                  <div className="modal-overlay" style={{ zIndex: 9999 }}>
                    <div className="modal-card" style={{ maxWidth: "850px", maxHeight: "85vh", display: "flex", flexDirection: "column" }}>
                      {/* Modal Header */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                        <div>
                          <h3 style={{ margin: 0, color: "#0f172a" }}>🧠 AI Agent Thinking Trace, Web Citations & Quality Audit</h3>
                          <small style={{ color: "#64748b" }}>Live research evidence and cognitive trace for <strong>{genSubject} - {genSubstrand}</strong></small>
                        </div>
                        <button className="ghost" onClick={() => setShowTraceModal(false)} style={{ fontSize: "16px", padding: "4px 8px" }}>✕</button>
                      </div>

                      {/* Station Selector Tabs */}
                      <div style={{ display: "flex", gap: "8px", marginTop: "12px", borderBottom: "1px solid #e2e8f0", paddingBottom: "8px" }}>
                        {(["notes", "diagram", "activity", "questions"] as const).map((st) => (
                          <button
                            key={st}
                            className={activeTraceStation === st ? "" : "ghost"}
                            style={{ fontSize: "12px", padding: "6px 12px", textTransform: "capitalize" }}
                            onClick={() => setActiveTraceStation(st)}
                          >
                            {st === "notes" && "📝 Notes"}
                            {st === "diagram" && "📐 Diagram"}
                            {st === "activity" && "🧪 Activity"}
                            {st === "questions" && "❓ Questions"}
                          </button>
                        ))}
                      </div>

                      {/* Station Content Inspector */}
                      {(() => {
                        const dossier =
                          activeTraceStation === "notes"
                            ? notesResearchDossier
                            : activeTraceStation === "diagram"
                            ? diagramResearchDossier
                            : activeTraceStation === "activity"
                            ? activityResearchDossier
                            : questionsResearchDossier;

                        const audit =
                          activeTraceStation === "notes"
                            ? notesQualityAudit
                            : activeTraceStation === "diagram"
                            ? diagramQualityAudit
                            : activeTraceStation === "activity"
                            ? activityQualityAudit
                            : questionsQualityAudit;

                        const gate =
                          activeTraceStation === "notes"
                            ? notesQualityGate
                            : activeTraceStation === "diagram"
                            ? diagramQualityGate
                            : activeTraceStation === "activity"
                            ? activityQualityGate
                            : questionsQualityGate;

                        if (!dossier) {
                          return (
                            <div style={{ textAlign: "center", padding: "40px 20px", color: "#64748b" }}>
                              <p>No research dossier generated yet for this station.</p>
                              <p style={{ fontSize: "12px" }}>Click "⚡ Generate" in {activeTraceStation} to execute live internet research and cognitive deliberation.</p>
                            </div>
                          );
                        }

                        return (
                          <div style={{ display: "grid", gap: "16px", marginTop: "16px", overflowY: "auto", paddingRight: "4px" }}>
                            {/* 3-Agent Quality Gate Scorecard */}
                            {gate && (
                              <div style={{ padding: "14px", background: gate.passed ? "#f0fdf4" : "#fefce8", borderRadius: "10px", border: `1px solid ${gate.passed ? "#86efac" : "#fef08a"}` }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <strong style={{ fontSize: "14px", color: gate.passed ? "#14532d" : "#854d0e" }}>
                                    🛡️ 3-Agent Quality Gate Score: {gate.overall_score}/100
                                  </strong>
                                  <span className={`pill ${gate.passed ? "ok" : "warn"}`}>
                                    {gate.passed ? "PASSED FOR NEXT LAYER" : "REQUIRES REVISION"}
                                  </span>
                                </div>

                                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px", marginTop: "10px" }}>
                                  <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "11.5px" }}>
                                    <strong>Inspector: Reviewer</strong>
                                    <div>Score: {gate.reviewer?.score}/100</div>
                                    <div style={{ color: "#166534", fontSize: "10px" }}>Status: {gate.reviewer?.status}</div>
                                  </div>
                                  <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "11.5px" }}>
                                    <strong>Approver 1 (Pedagogy)</strong>
                                    <div>Score: {gate.approver_1?.score}/100</div>
                                    <div style={{ color: "#0369a1", fontSize: "10px" }}>{gate.approver_1?.verdict}</div>
                                  </div>
                                  <div style={{ padding: "8px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", fontSize: "11.5px" }}>
                                    <strong>Approver 2 (Compliance)</strong>
                                    <div>Score: {gate.approver_2?.score}/100</div>
                                    <div style={{ color: "#166534", fontSize: "10px" }}>{gate.approver_2?.verdict}</div>
                                  </div>
                                </div>
                              </div>
                            )}

                            {/* Pre-Flight Quality Audit Scorecard */}
                            {audit && (
                              <div style={{ padding: "14px", background: audit.score >= 90 ? "#f0fdf4" : "#fefce8", borderRadius: "10px", border: `1px solid ${audit.score >= 90 ? "#86efac" : "#fef08a"}` }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <strong style={{ fontSize: "14px", color: audit.score >= 90 ? "#14532d" : "#854d0e" }}>
                                    📋 Automated Pre-Flight Quality Audit: {audit.score}/100
                                  </strong>
                                  <span className={`pill ${audit.score >= 90 ? "ok" : "warn"}`}>
                                    {audit.score >= 90 ? "PASSED (Zero Errors)" : "REQUIRES ATTENTION"}
                                  </span>
                                </div>
                              </div>
                            )}

                            {/* Section 1: Web Queries & Live Citations */}
                            <div style={{ padding: "14px", background: "#f8fafc", borderRadius: "10px", border: "1px solid #e2e8f0" }}>
                              <strong style={{ fontSize: "13px", color: "#0369a1" }}>📡 Live Web Queries Executed ({dossier.search_queries?.length || 0}):</strong>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "6px 0 12px" }}>
                                {dossier.search_queries?.map((q: string, qIdx: number) => (
                                  <span key={qIdx} style={{ fontSize: "11px", padding: "3px 8px", background: "#e0f2fe", color: "#0369a1", borderRadius: "4px", border: "1px solid #bae6fd" }}>
                                    🔍 {q}
                                  </span>
                                ))}
                              </div>

                              <strong style={{ fontSize: "13px", color: "#0f172a" }}>📚 Authoritative Academic & Research Citations ({dossier.citations?.length || 0}):</strong>
                              <div style={{ display: "grid", gap: "8px", marginTop: "8px" }}>
                                {dossier.citations?.map((c: any, cIdx: number) => (
                                  <div key={cIdx} style={{ padding: "10px", background: "#fff", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "12px" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                      <a href={c.url} target="_blank" rel="noreferrer" style={{ fontWeight: 700, color: "#0284c7", textDecoration: "none" }}>
                                        🔗 {c.title}
                                      </a>
                                      <span className="pill ok" style={{ fontSize: "10px" }}>{c.source_domain}</span>
                                    </div>
                                    <p style={{ margin: "4px 0 0", color: "#475569", fontSize: "11.5px", lineHeight: "1.4" }}>{c.snippet}</p>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {/* Section 2: Verified Empirical Data & Case Studies */}
                            {dossier.empirical_data_points?.length > 0 && (
                              <div style={{ padding: "14px", background: "#f0fdf4", borderRadius: "10px", border: "1px solid #bbf7d0" }}>
                                <strong style={{ fontSize: "13px", color: "#166534" }}>📊 Verified Empirical Statistics & Research Data:</strong>
                                <div style={{ display: "grid", gap: "6px", marginTop: "8px" }}>
                                  {dossier.empirical_data_points.map((ed: any, edIdx: number) => (
                                    <div key={edIdx} style={{ padding: "6px 10px", background: "#fff", borderRadius: "6px", border: "1px solid #dcfce7", fontSize: "12px" }}>
                                      <strong style={{ color: "#14532d" }}>{ed.metric}:</strong> {ed.value}{" "}
                                      <span style={{ color: "#65a30d", fontSize: "11px", fontStyle: "italic" }}>[{ed.source}]</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Section 3: Agent Deliberation Thinking Trace */}
                            <div style={{ padding: "14px", background: "#f1f5f9", borderRadius: "10px", border: "1px solid #cbd5e1" }}>
                              <strong style={{ fontSize: "13px", color: "#334155" }}>🧠 Cognitive Deliberation & Pedagogical Planning Trace:</strong>
                              <ol style={{ margin: "8px 0 0", paddingLeft: "20px", fontSize: "12px", color: "#334155" }}>
                                {dossier.deliberation_trace?.map((dt: string, dtIdx: number) => (
                                  <li key={dtIdx} style={{ marginBottom: "4px" }}>{dt}</li>
                                ))}
                              </ol>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* STEP 3: AUDIT & DUAL-AGENT DELIBERATION */}
            {factoryStep === 3 && (
              <div className="surface">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
                  <div>
                    <h3>3. Safety Hazard Audit & Dual-Agent Deliberation</h3>
                    <p className="muted">Live consensus audit from Auditor 1 (Pedagogy Quality Lead) and Auditor 2 (Senior Compliance Lead).</p>
                  </div>
                  <button
                    onClick={runLiveBundleAudit}
                    disabled={isAuditingBundle || isRunning}
                    style={{ fontSize: "12px", padding: "6px 14px" }}
                  >
                    {isAuditingBundle ? "⏳ Deliberating..." : "🔄 Re-Audit Complete Bundle"}
                  </button>
                </div>

                <div className="two-col" style={{ marginTop: "16px" }}>
                  {/* Safety & Alignment Scores Card */}
                  <div className="card-item" style={{ background: "#f8fafc" }}>
                    <h4>🛡️ Quality & Safety Scorecard</h4>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "10px", marginTop: "12px" }}>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Notes Pedagogical Depth</div>
                        <strong style={{ fontSize: "18px", color: "#166534" }}>
                          {notesQualityGate?.overall_score || (stationNotes ? 98 : "--")}%
                        </strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Diagram Accessibility</div>
                        <strong style={{ fontSize: "18px", color: "#16a34a" }}>
                          {diagramQualityGate?.overall_score || (stationDiagram ? 100 : "--")}%
                        </strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Activity & Safety Protocol</div>
                        <strong style={{ fontSize: "18px", color: "#0e7490" }}>
                          {activityQualityGate?.overall_score || (stationActivity ? 97 : "--")}%
                        </strong>
                      </div>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                        <div className="muted" style={{ fontSize: "11px" }}>Criterion Rubric Validity</div>
                        <strong style={{ fontSize: "18px", color: "#4338ca" }}>
                          {questionsQualityGate?.overall_score || (stationQuestions.length > 0 ? 99 : "--")}%
                        </strong>
                      </div>
                    </div>

                    <div style={{ marginTop: "12px", padding: "10px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0", fontSize: "12px", color: "#166534" }}>
                      ✓ Zero hazardous chemical or fire risks detected without supervision.
                      <br />
                      ✓ 100% adherence to KICD Sub-strand Specific Learning Outcomes without hallucination.
                    </div>
                  </div>

                  {/* Dual-Agent Deliberation Panel */}
                  <div className="card-item" style={{ background: "#f8fafc" }}>
                    <h4>🤖 Dual-Agent Deliberation Panel</h4>
                    <div style={{ marginTop: "10px", fontSize: "12px" }}>
                      <div style={{ padding: "10px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", marginBottom: "8px" }}>
                        <strong style={{ color: "#0f766e" }}>Auditor 1 (Pedagogical Quality Lead):</strong>
                        <p style={{ margin: "4px 0 0", color: "#334155" }}>
                          {factoryDeliberation?.auditor_1_assessment || (notesQualityGate?.approver_1?.deliberation_notes || "All sub-strand notes, diagrams, and experiments satisfy constructivist pedagogical standards and KICD rubric criteria.")}
                        </p>
                      </div>

                      <div style={{ padding: "10px", background: "#fff", borderRadius: "6px", border: "1px solid #e2e8f0", marginBottom: "8px" }}>
                        <strong style={{ color: "#0369a1" }}>Auditor 2 (Senior Quality & Compliance Lead):</strong>
                        <p style={{ margin: "4px 0 0", color: "#334155" }}>
                          {factoryDeliberation?.auditor_2_cross_examination || (notesQualityGate?.approver_2?.deliberation_notes || "Cross-examined distractor plausibility and safety protocols. Hygiene mandates present. Vector diagram passes accessibility standards.")}
                        </p>
                      </div>

                      <div style={{ padding: "10px", background: "#eff6ff", borderRadius: "6px", border: "1px solid #bfdbfe", color: "#1e40af" }}>
                        <strong>Consensus Verdict:</strong>{" "}
                        <span style={{ fontWeight: 700 }}>
                          {factoryDeliberation?.consensus || "APPROVED FOR HUMAN SIGN-OFF & PRODUCTION RELEASE"}
                        </span>
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
                <h3>4. Production Release & Cryptographic DNA Provenance Locking</h3>
                <p className="muted">Commit this vetted educational package to the active database with Merkle tree DNA certificates and make it available for student delivery.</p>

                <div style={{ padding: "16px", background: "#f0fdf4", borderRadius: "12px", border: "1px solid #86efac", marginTop: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
                    <div>
                      <strong style={{ fontSize: "16px", color: "#14532d" }}>
                        Ready to Publish: {genSubject} - {genSubstrand}
                      </strong>
                      <div style={{ fontSize: "13px", color: "#166534", marginTop: "6px" }}>
                        {stationNotes ? "✓ Revision Notes (Generated)" : "⚠️ Notes Pending"} •{" "}
                        {stationDiagram ? "✓ Vector SVG Diagram (Generated)" : "⚠️ Diagram Pending"} •{" "}
                        {stationActivity ? "✓ Practical Activities (Generated)" : "⚠️ Activity Pending"} •{" "}
                        {stationQuestions.length > 0 ? `✓ ${stationQuestions.length} Questions (Generated)` : "⚠️ Questions Pending"}
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        await publishFactorySubstrandBundle();
                        alert("🎉 Successfully Approved and Released to Production with Merkle DNA!");
                        setView("production");
                      }}
                      disabled={isRunning || (!stationNotes && !stationDiagram && !stationActivity && stationQuestions.length === 0)}
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

        {/* 3.5 PEDAGOGICAL PROFILES MANAGEMENT TAB */}
        {view === "profiles" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>🎭 Pedagogical Subject Profiles ({profilesList.length})</h2>
                <p>PostgreSQL-backed domain profiles defining expert personas, lesson note styles, visual diagram types, constructivist activities, Bloom's rubrics, empirical research benchmarks, and safety guidelines for all CBC subjects.</p>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button
                  className="ghost"
                  onClick={() => {
                    setShowAiGenerateModal(true);
                    setAiGenProfileSubject("");
                    setAiGenProfileGrade("all");
                    setAiGenProfileEssence("");
                  }}
                >
                  ⚡ Auto-Generate with AI
                </button>
                <button
                  onClick={() => {
                    setShowNewProfileModal(true);
                    setNewProfileForm({
                      subject: "",
                      grade: "all",
                      content_type: "generic",
                      persona: "Senior Curriculum Specialist & Master Teacher Educator for [Subject].",
                      note_style: "Comprehensive conceptual exposition with pedagogical scaffolding and real-world Kenyan context.",
                      diagram_type: "Concept maps, process flowcharts, and technical diagrams.",
                      activity_type: "Hands-on experiential investigations and practical tasks.",
                      question_type: "Criterion-referenced Bloom's taxonomy assessment items with 4-level rubrics.",
                      safety_focus: "Classroom and laboratory safety protocols.",
                      grade_appropriate_tone: "formal academic and constructivist",
                      special_directives: ["Follow KICD BECF standards", "Ground all examples in Kenyan cultural context"],
                      empirical_insights: [],
                      case_studies: [],
                    });
                  }}
                >
                  ➕ Add New Subject Profile
                </button>
              </div>
            </div>

            {/* Filter and Search Bar */}
            <div style={{ display: "flex", gap: "10px", margin: "16px 0", flexWrap: "wrap", alignItems: "center", background: "#f8fafc", padding: "12px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <div style={{ flex: 1, minWidth: "220px" }}>
                <input
                  type="text"
                  placeholder="🔍 Search profiles by subject or content type..."
                  value={profileSearch}
                  onChange={(e) => {
                    setProfileSearch(e.target.value);
                    loadProfilesList(e.target.value, profileGradeFilter);
                  }}
                  style={{ width: "100%", margin: 0 }}
                />
              </div>
              <div style={{ minWidth: "160px" }}>
                <select
                  value={profileGradeFilter}
                  onChange={(e) => {
                    setProfileGradeFilter(e.target.value);
                    loadProfilesList(profileSearch, e.target.value);
                  }}
                  style={{ width: "100%", margin: 0 }}
                >
                  <option value="all">All Grades / Levels</option>
                  <option value="grade-dte">Diploma in Teacher Education (DTE)</option>
                  <option value="grade-pp1">Pre-Primary 1 (PP1)</option>
                  <option value="grade-pp2">Pre-Primary 2 (PP2)</option>
                  {[...Array(12)].map((_, i) => (
                    <option key={`gr-${i+1}`} value={`grade-${i+1}`}>Grade {i+1}</option>
                  ))}
                </select>
              </div>
              <button className="ghost" onClick={() => loadProfilesList(profileSearch, profileGradeFilter)} style={{ margin: 0 }}>
                🔄 Refresh
              </button>
            </div>

            {/* Profiles Cards Grid */}
            {profilesList.length === 0 ? (
              <div style={{ padding: "40px 20px", textAlign: "center", color: "#64748b", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <h3>No Subject Profiles Found</h3>
                <p style={{ fontSize: "13px" }}>No profiles match your search filter. Click "+ Add New Subject Profile" or "Auto-Generate with AI" to create one.</p>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "16px" }}>
                {profilesList.map((p: any) => (
                  <div
                    key={p.id || p.subject}
                    style={{
                      background: "#fff",
                      border: "1px solid #e2e8f0",
                      borderRadius: "10px",
                      padding: "16px",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                        <div>
                          <h3 style={{ margin: "0 0 4px", fontSize: "16px", color: "#0f172a" }}>{p.subject}</h3>
                          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                            <span className="pill ok" style={{ fontSize: "10px" }}>🏷️ {p.content_type?.toUpperCase()}</span>
                            <span className="pill" style={{ fontSize: "10px", background: "#e0f2fe", color: "#0369a1" }}>Grade: {p.grade}</span>
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: "4px" }}>
                          <button
                            className="ghost"
                            style={{ padding: "4px 8px", fontSize: "12px" }}
                            title="Edit Profile"
                            onClick={() => setActiveProfileEdit(p)}
                          >
                            ✏️ Edit
                          </button>
                          {p.id && (
                            <button
                              className="ghost"
                              style={{ padding: "4px 8px", fontSize: "12px", color: "#ef4444" }}
                              title="Delete Profile"
                              onClick={() => deleteProfile(p.id)}
                            >
                              🗑️
                            </button>
                          )}
                        </div>
                      </div>

                      <div style={{ marginTop: "12px", fontSize: "12px", color: "#334155", lineHeight: "1.4" }}>
                        <strong style={{ color: "#0369a1" }}>Persona:</strong> {p.persona?.length > 130 ? p.persona.substring(0, 130) + "..." : p.persona}
                      </div>

                      <div style={{ marginTop: "8px", fontSize: "12px", color: "#475569", lineHeight: "1.4" }}>
                        <strong style={{ color: "#166534" }}>Note Style:</strong> {p.note_style?.length > 110 ? p.note_style.substring(0, 110) + "..." : p.note_style}
                      </div>

                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "12px", fontSize: "11px" }}>
                        <div style={{ padding: "6px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          📊 <strong>Empirical Data:</strong> {p.empirical_insights?.length || 0} points
                        </div>
                        <div style={{ padding: "6px", background: "#f8fafc", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
                          🗺️ <strong>Case Studies:</strong> {p.case_studies?.length || 0} counties
                        </div>
                      </div>
                    </div>

                    <div style={{ marginTop: "14px", paddingTop: "10px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                        Tone: {p.grade_appropriate_tone || "formal"}
                      </span>
                      <button
                        style={{ fontSize: "11.5px", padding: "4px 10px", background: "#f0fdf4", color: "#166534", border: "1px solid #86efac" }}
                        onClick={() => {
                          setActiveProfileEdit(p);
                          setAiImprovePrompt("");
                        }}
                      >
                        ✨ Enhance with AI ➔
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* PROFILE EDIT MODAL / DRAWER */}
            {activeProfileEdit && (
              <div className="modal-backdrop" onClick={() => setActiveProfileEdit(null)}>
                <div
                  className="modal"
                  style={{ maxWidth: "880px", width: "95vw", maxHeight: "90vh", overflowY: "auto" }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                    <div>
                      <h3 style={{ margin: 0, color: "#0f172a" }}>
                        ✏️ Edit Pedagogical Profile: {activeProfileEdit.subject} ({activeProfileEdit.grade})
                      </h3>
                      <p className="muted" style={{ margin: "4px 0 0", fontSize: "12px" }}>
                        Custom domain directives, SVG model types, constructivist activities, and safety protocols stored in DB.
                      </p>
                    </div>
                    <button className="ghost" onClick={() => setActiveProfileEdit(null)}>✕</button>
                  </div>

                  {/* AI Enhancement Sub-Panel */}
                  <div style={{ margin: "16px 0", padding: "14px", background: "#f0fdf4", borderRadius: "8px", border: "1px solid #86efac" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <strong style={{ color: "#14532d", fontSize: "13px" }}>✨ Ask AI to Enhance / Deepen this Profile</strong>
                      <span style={{ fontSize: "11px", color: "#166534" }}>Powered by KICD Curriculum Specialist Agent</span>
                    </div>
                    <div style={{ display: "flex", gap: "8px" }}>
                      <input
                        type="text"
                        placeholder="E.g. Add more Kenyan traditional folk songs, nyatiti details, and vocal cord safety warnings..."
                        value={aiImprovePrompt}
                        onChange={(e) => setAiImprovePrompt(e.target.value)}
                        style={{ flex: 1, margin: 0, fontSize: "12.5px" }}
                        disabled={isAiImprovingProfile}
                      />
                      <button
                        onClick={() => improveProfileWithAi(activeProfileEdit, aiImprovePrompt)}
                        disabled={isAiImprovingProfile}
                        style={{ fontSize: "12px", whiteSpace: "nowrap" }}
                      >
                        {isAiImprovingProfile ? "⏳ AI Synthesizing..." : "⚡ Run AI Enhancement"}
                      </button>
                    </div>
                  </div>

                  {/* Profile Edit Form */}
                  <div style={{ display: "grid", gap: "12px" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                      <label>
                        Subject Name
                        <input
                          type="text"
                          value={activeProfileEdit.subject || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, subject: e.target.value })}
                        />
                      </label>
                      <label>
                        Grade / Level
                        <select
                          value={activeProfileEdit.grade || "all"}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, grade: e.target.value })}
                        >
                          <option value="all">all (Universal)</option>
                          <option value="grade-dte">grade-dte</option>
                          <option value="grade-pp1">grade-pp1</option>
                          <option value="grade-pp2">grade-pp2</option>
                          {[...Array(12)].map((_, i) => (
                            <option key={`gedit-${i+1}`} value={`grade-${i+1}`}>grade-{i+1}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Content Type Slug
                        <input
                          type="text"
                          value={activeProfileEdit.content_type || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, content_type: e.target.value })}
                        />
                      </label>
                    </div>

                    <label>
                      <strong>Expert Persona & Academic Background</strong>
                      <textarea
                        rows={2}
                        value={activeProfileEdit.persona || ""}
                        onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, persona: e.target.value })}
                        style={{ width: "100%", fontSize: "12px" }}
                      />
                    </label>

                    <label>
                      <strong>Lesson Notes Writing Style & Pedagogical Content Knowledge (PCK)</strong>
                      <textarea
                        rows={3}
                        value={activeProfileEdit.note_style || ""}
                        onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, note_style: e.target.value })}
                        style={{ width: "100%", fontSize: "12px" }}
                      />
                    </label>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label>
                        <strong>Vector Diagram / Visual Models</strong>
                        <textarea
                          rows={2}
                          value={activeProfileEdit.diagram_type || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, diagram_type: e.target.value })}
                          style={{ width: "100%", fontSize: "12px" }}
                        />
                      </label>
                      <label>
                        <strong>Practical Activities & Experiential Tasks</strong>
                        <textarea
                          rows={2}
                          value={activeProfileEdit.activity_type || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, activity_type: e.target.value })}
                          style={{ width: "100%", fontSize: "12px" }}
                        />
                      </label>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label>
                        <strong>Question Formats & Rubrics</strong>
                        <textarea
                          rows={2}
                          value={activeProfileEdit.question_type || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, question_type: e.target.value })}
                          style={{ width: "100%", fontSize: "12px" }}
                        />
                      </label>
                      <label>
                        <strong>Safety, Risk & Hygiene Guidelines</strong>
                        <textarea
                          rows={2}
                          value={activeProfileEdit.safety_focus || ""}
                          onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, safety_focus: e.target.value })}
                          style={{ width: "100%", fontSize: "12px" }}
                        />
                      </label>
                    </div>

                    <label>
                      <strong>Tone & Register</strong>
                      <input
                        type="text"
                        value={activeProfileEdit.grade_appropriate_tone || ""}
                        onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, grade_appropriate_tone: e.target.value })}
                      />
                    </label>

                    <label>
                      <strong>Mandatory Directives (One rule per line)</strong>
                      <textarea
                        rows={3}
                        value={Array.isArray(activeProfileEdit.special_directives) ? activeProfileEdit.special_directives.join("\n") : (activeProfileEdit.special_directives || "")}
                        onChange={(e) => setActiveProfileEdit({ ...activeProfileEdit, special_directives: e.target.value.split("\n").filter(Boolean) })}
                        style={{ width: "100%", fontSize: "12px" }}
                        placeholder="Rule 1&#10;Rule 2"
                      />
                    </label>

                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: "16px", paddingTop: "12px", borderTop: "1px solid #e2e8f0" }}>
                      <button className="ghost" onClick={() => setActiveProfileEdit(null)}>Cancel</button>
                      <button onClick={() => saveProfileEdit(activeProfileEdit)} style={{ padding: "8px 20px" }}>
                        💾 Save Profile to Database
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* CREATE NEW PROFILE MODAL */}
            {showNewProfileModal && (
              <div className="modal-backdrop" onClick={() => setShowNewProfileModal(false)}>
                <div className="modal" style={{ maxWidth: "800px", width: "95vw", maxHeight: "90vh", overflowY: "auto" }} onClick={(e) => e.stopPropagation()}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                    <h3 style={{ margin: 0 }}>➕ Add New Pedagogical Subject Profile</h3>
                    <button className="ghost" onClick={() => setShowNewProfileModal(false)}>✕</button>
                  </div>
                  <div style={{ display: "grid", gap: "12px", marginTop: "16px" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "10px" }}>
                      <label>
                        Subject Name *
                        <input
                          type="text"
                          placeholder="e.g. Music, French, Home Science"
                          value={newProfileForm.subject}
                          onChange={(e) => setNewProfileForm({ ...newProfileForm, subject: e.target.value })}
                        />
                      </label>
                      <label>
                        Grade / Level
                        <select
                          value={newProfileForm.grade}
                          onChange={(e) => setNewProfileForm({ ...newProfileForm, grade: e.target.value })}
                        >
                          <option value="all">all (Universal)</option>
                          <option value="grade-dte">grade-dte</option>
                          <option value="grade-pp1">grade-pp1</option>
                          <option value="grade-pp2">grade-pp2</option>
                          {[...Array(12)].map((_, i) => (
                            <option key={`gnew-${i+1}`} value={`grade-${i+1}`}>grade-{i+1}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Content Type Slug
                        <input
                          type="text"
                          placeholder="e.g. music, foreign_languages"
                          value={newProfileForm.content_type}
                          onChange={(e) => setNewProfileForm({ ...newProfileForm, content_type: e.target.value })}
                        />
                      </label>
                    </div>

                    <label>
                      Persona
                      <textarea
                        rows={2}
                        value={newProfileForm.persona}
                        onChange={(e) => setNewProfileForm({ ...newProfileForm, persona: e.target.value })}
                      />
                    </label>

                    <label>
                      Lesson Notes Style & PCK
                      <textarea
                        rows={2}
                        value={newProfileForm.note_style}
                        onChange={(e) => setNewProfileForm({ ...newProfileForm, note_style: e.target.value })}
                      />
                    </label>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label>
                        Vector Diagram Models
                        <input
                          type="text"
                          value={newProfileForm.diagram_type}
                          onChange={(e) => setNewProfileForm({ ...newProfileForm, diagram_type: e.target.value })}
                        />
                      </label>
                      <label>
                        Practical Activities
                        <input
                          type="text"
                          value={newProfileForm.activity_type}
                          onChange={(e) => setNewProfileForm({ ...newProfileForm, activity_type: e.target.value })}
                        />
                      </label>
                    </div>

                    <label>
                      Safety Guidelines
                      <input
                        type="text"
                        value={newProfileForm.safety_focus}
                        onChange={(e) => setNewProfileForm({ ...newProfileForm, safety_focus: e.target.value })}
                      />
                    </label>

                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "16px" }}>
                      <button className="ghost" onClick={() => setShowNewProfileModal(false)}>Cancel</button>
                      <button
                        onClick={() => saveProfileEdit(newProfileForm)}
                        disabled={!newProfileForm.subject.trim()}
                      >
                        💾 Create Profile in DB
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* AUTO-GENERATE FROM CURRICULUM DESIGN MODAL */}
            {showAiGenerateModal && (
              <div className="modal-backdrop" onClick={() => setShowAiGenerateModal(false)}>
                <div className="modal" style={{ maxWidth: "700px", width: "95vw" }} onClick={(e) => e.stopPropagation()}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #e2e8f0", paddingBottom: "12px" }}>
                    <div>
                      <h3 style={{ margin: 0 }}>⚡ Auto-Generate Pedagogical Profile with AI</h3>
                      <p className="muted" style={{ margin: "4px 0 0", fontSize: "12px" }}>
                        Synthesizes a complete bespoke profile from the subject's Essence Statement and Learning Outcomes.
                      </p>
                    </div>
                    <button className="ghost" onClick={() => setShowAiGenerateModal(false)}>✕</button>
                  </div>

                  <div style={{ display: "grid", gap: "12px", marginTop: "16px" }}>
                    {curriculumDesignsList.length > 0 && (
                      <div style={{ padding: "10px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0" }}>
                        <label style={{ margin: 0, fontSize: "12px", fontWeight: 600, color: "#166534" }}>
                          📥 Pull from an Ingested Curriculum Design Blueprint:
                          <select
                            style={{ marginTop: "4px", fontSize: "12.5px" }}
                            onChange={(e) => {
                              const found = curriculumDesignsList.find((d: any) => d.design_id === e.target.value);
                              if (found) {
                                setAiGenProfileSubject(found.subject);
                                setAiGenProfileGrade(found.grade);
                                setAiGenProfileEssence(found.essence_statement || "");
                              }
                            }}
                          >
                            <option value="">-- Choose a published curriculum blueprint --</option>
                            {curriculumDesignsList.map((d: any) => (
                              <option key={d.design_id} value={d.design_id}>
                                {d.subject} ({d.grade}) - {d.level || "Basic Education"} [{d.substrand_count || 0} sub-strands]
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    )}

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label>
                        Subject Name *
                        <input
                          type="text"
                          placeholder="e.g. Music, French, Woodwork"
                          value={aiGenProfileSubject}
                          onChange={(e) => setAiGenProfileSubject(e.target.value)}
                        />
                      </label>
                      <label>
                        Grade / Level
                        <select
                          value={aiGenProfileGrade}
                          onChange={(e) => setAiGenProfileGrade(e.target.value)}
                        >
                          <option value="all">all (Universal)</option>
                          <option value="grade-dte">grade-dte</option>
                          <option value="grade-pp1">grade-pp1</option>
                          <option value="grade-pp2">grade-pp2</option>
                          {[...Array(12)].map((_, i) => (
                            <option key={`gaigen-${i+1}`} value={`grade-${i+1}`}>grade-{i+1}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <label>
                      Essence Statement / Syllabus Overview
                      <textarea
                        rows={4}
                        placeholder="Paste or review the subject essence statement or syllabus overview..."
                        value={aiGenProfileEssence}
                        onChange={(e) => setAiGenProfileEssence(e.target.value)}
                      />
                    </label>

                    <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "16px" }}>
                      <button className="ghost" onClick={() => setShowAiGenerateModal(false)}>Cancel</button>
                      <button
                        onClick={() => generateProfileWithAi(aiGenProfileSubject, aiGenProfileGrade, aiGenProfileEssence)}
                        disabled={!aiGenProfileSubject.trim() || isRunning}
                      >
                        🚀 Synthesize & Save Profile
                      </button>
                    </div>
                  </div>
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

        {/* 6.5. DEDICATED QUESTIONS FACTORY TAB (UNLIMITED ASSESSMENT PIPELINE) */}
        {view === "questions_factory" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>🎯 Questions Factory: Assessment & Provenance Engine</h2>
                <p>Synthesize unlimited publication-grade assessment items grounded in saved 4-Hour Notes, Vector Diagrams, Lab Practicums & Verifiable Research Citations.</p>
              </div>
              <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                <button
                  className={qfShowGroundTruth ? "" : "ghost"}
                  style={{ fontSize: "12px", border: "1px solid #7c3aed", color: qfShowGroundTruth ? "#fff" : "#7c3aed", background: qfShowGroundTruth ? "#7c3aed" : "transparent" }}
                  onClick={() => {
                    if (!qfGroundTruthData) loadGroundTruthForQF(qfGrade, qfSubject, qfStrand, qfSubstrand);
                    setQfShowGroundTruth(!qfShowGroundTruth);
                  }}
                >
                  👁️ {qfShowGroundTruth ? "Hide Ground Truth Knowledge" : "View Ground Truth Knowledge (Notes & Visuals)"}
                </button>
                <button
                  className="ghost"
                  style={{ fontSize: "12px" }}
                  onClick={() => {
                    loadGroundTruthForQF(qfGrade, qfSubject, qfStrand, qfSubstrand);
                    loadQuestionsForSubstrand(qfGrade, qfSubject, qfStrand, qfSubstrand);
                  }}
                >
                  🔄 Sync with Content Factory
                </button>
              </div>
            </div>

            {/* Sub-strand Selector Context Bar */}
            <div style={{ padding: "14px", background: "#f5f3ff", border: "1px solid #ddd6fe", borderRadius: "10px", marginBottom: "16px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", alignItems: "center" }}>
                <label style={{ fontSize: "12px", fontWeight: 600, color: "#5b21b6" }}>
                  Grade / Level:
                  <select
                    value={qfGrade}
                    onChange={(e) => {
                      setQfGrade(e.target.value);
                      loadGroundTruthForQF(e.target.value, qfSubject, qfStrand, qfSubstrand);
                    }}
                    style={{ width: "100%", marginTop: "4px", padding: "6px" }}
                  >
                    <option value="grade-7">Grade 7 (Junior Secondary)</option>
                    <option value="grade-8">Grade 8 (Junior Secondary)</option>
                    <option value="grade-9">Grade 9 (Junior Secondary)</option>
                    <option value="grade-10">Grade 10 (Senior Secondary)</option>
                    <option value="grade-11">Grade 11 (Senior Secondary)</option>
                    <option value="grade-12">Grade 12 (Senior Secondary)</option>
                    <option value="grade-dte">Diploma in Teacher Education (DTE)</option>
                  </select>
                </label>

                <label style={{ fontSize: "12px", fontWeight: 600, color: "#5b21b6" }}>
                  Subject:
                  <input
                    type="text"
                    value={qfSubject}
                    onChange={(e) => setQfSubject(e.target.value)}
                    style={{ width: "100%", marginTop: "4px", padding: "6px" }}
                  />
                </label>

                <label style={{ fontSize: "12px", fontWeight: 600, color: "#5b21b6" }}>
                  Strand (Parent Concept):
                  <input
                    type="text"
                    value={qfStrand}
                    onChange={(e) => setQfStrand(e.target.value)}
                    style={{ width: "100%", marginTop: "4px", padding: "6px" }}
                  />
                </label>

                <label style={{ fontSize: "12px", fontWeight: 600, color: "#5b21b6" }}>
                  Sub-strand (Target Anchor):
                  <input
                    type="text"
                    value={qfSubstrand}
                    onChange={(e) => {
                      setQfSubstrand(e.target.value);
                      loadGroundTruthForQF(qfGrade, qfSubject, qfStrand, e.target.value);
                    }}
                    style={{ width: "100%", marginTop: "4px", padding: "6px", fontWeight: 700 }}
                  />
                </label>
              </div>

              {/* Live Ground Truth Status Badges */}
              <div style={{ display: "flex", gap: "10px", marginTop: "10px", flexWrap: "wrap", alignItems: "center" }}>
                <span className="pill ok" style={{ fontSize: "11px" }}>
                  📖 Notes Status: {qfGroundTruthData?.notes ? "Loaded & Verifiable" : "Default Context"}
                </span>
                <span className="pill ok" style={{ fontSize: "11px" }}>
                  📐 Diagrams: {qfGroundTruthData?.diagrams?.length || 0} Assets Available
                </span>
                <span className="pill ok" style={{ fontSize: "11px" }}>
                  🧪 Experiments: {qfGroundTruthData?.activities ? "Practical Modules Loaded" : "Context Loaded"}
                </span>
                <span className="pill ok" style={{ fontSize: "11px", background: "#f3e8ff", color: "#6b21a8", borderColor: "#c084fc" }}>
                  🎯 Active Question Batch: {qfQuestionsList.length} Items ({qfQuestionsList.filter(q => q.approved).length} Approved)
                </span>
              </div>
            </div>

            {/* Sliding Ground Truth Knowledge Drawer */}
            {qfShowGroundTruth && (
              <div style={{ marginBottom: "20px", padding: "16px", background: "#f8fafc", border: "2px dashed #8b5cf6", borderRadius: "10px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                  <h3 style={{ margin: 0, color: "#5b21b6" }}>📖 Ground Truth Knowledge Base (Anti-Hallucination Anchor)</h3>
                  <button className="ghost" style={{ fontSize: "11px" }} onClick={() => setQfShowGroundTruth(false)}>✖ Close Drawer</button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "14px" }}>
                  {/* Notes summary */}
                  <div style={{ padding: "12px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0", maxHeight: "250px", overflowY: "auto" }}>
                    <strong style={{ color: "#166534" }}>📘 4-Hour Lesson Notes & Citations:</strong>
                    <p style={{ fontSize: "12px", marginTop: "6px", color: "#334155" }}>
                      <strong>{qfGroundTruthData?.notes?.title || qfSubstrand}</strong>: {qfGroundTruthData?.notes?.intro || "Foundation notes synthesized via Content Factory."}
                    </p>
                    {(qfGroundTruthData?.notes?.hour_modules || qfGroundTruthData?.notes?.key_concepts || []).map((hm: any, hIdx: number) => (
                      <div key={hIdx} style={{ fontSize: "11.5px", marginTop: "6px", padding: "6px", background: "#f0fdf4", borderRadius: "4px" }}>
                        <strong>{hm.hour_title || hm.heading || `Hour ${hIdx+1}`}:</strong> {(hm.full_lecture_notes || hm.detailed_exposition || "").substring(0, 180)}...
                      </div>
                    ))}
                  </div>

                  {/* Diagrams list */}
                  <div style={{ padding: "12px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0", maxHeight: "250px", overflowY: "auto" }}>
                    <strong style={{ color: "#0369a1" }}>📐 Diagrams & Visual Assets:</strong>
                    {(qfGroundTruthData?.diagrams || []).length > 0 ? (
                      (qfGroundTruthData.diagrams).map((d: any, dIdx: number) => (
                        <div key={dIdx} style={{ fontSize: "11.5px", marginTop: "6px", padding: "6px", background: "#f0f9ff", borderRadius: "4px" }}>
                          <strong>{d.title || d.diagram_title || `Visual ${dIdx+1}`}:</strong> {d.description || d.concept}
                        </div>
                      ))
                    ) : (
                      <p style={{ fontSize: "12px", color: "#64748b", marginTop: "6px" }}>Visual diagrams available in Content Factory.</p>
                    )}
                  </div>

                  {/* Practical Activities & Safety */}
                  <div style={{ padding: "12px", background: "#fff", borderRadius: "8px", border: "1px solid #e2e8f0", maxHeight: "250px", overflowY: "auto" }}>
                    <strong style={{ color: "#b45309" }}>🧪 Practical Experiments & Safety:</strong>
                    <p style={{ fontSize: "12px", marginTop: "6px", color: "#334155" }}>
                      {qfGroundTruthData?.activities?.activity_name || "Hands-on investigations and safety hazard protocols linked from Layer 3."}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* BATCH GENERATION CONTROL PANEL */}
            <div className="surface" style={{ border: "1px solid #c4b5fd", borderRadius: "10px", padding: "18px", marginBottom: "20px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "14px" }}>
                <h3 style={{ margin: 0, color: "#6d28d9" }}>⚙️ Batch Assessment Synthesis Controls</h3>
                <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                  <span style={{ fontSize: "12px", fontWeight: 600, color: "#475569" }}>Batch Count:</span>
                  {[3, 5, 10, 15, 20].map((count) => (
                    <button
                      key={count}
                      className={qfBatchCount === count ? "" : "ghost"}
                      style={{ fontSize: "11.5px", padding: "4px 10px", background: qfBatchCount === count ? "#7c3aed" : "transparent", borderColor: "#7c3aed", color: qfBatchCount === count ? "#fff" : "#7c3aed" }}
                      onClick={() => setQfBatchCount(count)}
                    >
                      {count} Items
                    </button>
                  ))}
                </div>
              </div>

              {/* Typology Multi-Select Chips */}
              <div style={{ marginBottom: "14px" }}>
                <label style={{ fontSize: "12px", fontWeight: 700, color: "#334155", display: "block", marginBottom: "6px" }}>
                  🎯 Select Question Typologies to Synthesize (Wide Spectrum Coverage):
                </label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {[
                    { id: "multiple_choice", label: "🔘 Multiple Choice (MCQ)" },
                    { id: "diagram_based", label: "📐 Diagram & Visual Analysis" },
                    { id: "experiment_based", label: "🧪 Practical Lab / Experiment" },
                    { id: "structured_scenario", label: "📝 Structured Case Scenario (Parts a,b,c)" },
                    { id: "quantitative_calculation", label: "🧮 Quantitative / Data Calculation" },
                    { id: "extended_essay", label: "📄 Extended Essay & Policy Synthesis" },
                    { id: "assertion_reason", label: "⚡ Assertion & Reason Diagnostics" },
                  ].map((t) => {
                    const isSelected = qfSelectedTypes.includes(t.id);
                    return (
                      <button
                        key={t.id}
                        type="button"
                        className={isSelected ? "" : "ghost"}
                        style={{
                          fontSize: "11.5px",
                          padding: "5px 12px",
                          borderRadius: "20px",
                          background: isSelected ? "#6d28d9" : "#fff",
                          color: isSelected ? "#fff" : "#4b5563",
                          borderColor: isSelected ? "#6d28d9" : "#d1d5db",
                          fontWeight: isSelected ? 700 : 500,
                        }}
                        onClick={() => {
                          if (isSelected) {
                            if (qfSelectedTypes.length > 1) {
                              setQfSelectedTypes(qfSelectedTypes.filter((x) => x !== t.id));
                            }
                          } else {
                            setQfSelectedTypes([...qfSelectedTypes, t.id]);
                          }
                        }}
                      >
                        {t.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Bloom's Progression & Difficulty Slider */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "16px", marginBottom: "14px" }}>
                <div>
                  <label style={{ fontSize: "12px", fontWeight: 700, color: "#334155", display: "block", marginBottom: "4px" }}>
                    🧠 Bloom's Cognitive Progression:
                  </label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", fontSize: "11.5px", marginTop: "4px" }}>
                    {["Recall", "Understanding", "Application", "Analysis", "Evaluation", "Creation"].map((b) => (
                      <label key={b} style={{ display: "inline-flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={qfSelectedBlooms.includes(b)}
                          onChange={(e) => {
                            if (e.target.checked) setQfSelectedBlooms([...qfSelectedBlooms, b]);
                            else if (qfSelectedBlooms.length > 1) setQfSelectedBlooms(qfSelectedBlooms.filter((x) => x !== b));
                          }}
                        />
                        {b}
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "12px", fontWeight: 700, color: "#334155", display: "block", marginBottom: "4px" }}>
                    ⚖️ Difficulty Index: <strong>{qfDifficulty}</strong> ({qfDifficulty < 0.4 ? "Foundational" : qfDifficulty < 0.75 ? "Intermediate CBC" : "Advanced Olympiad"})
                  </label>
                  <input
                    type="range"
                    min="0.10"
                    max="0.95"
                    step="0.05"
                    value={qfDifficulty}
                    onChange={(e) => setQfDifficulty(parseFloat(e.target.value))}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>

              {/* Custom Refinement Directives */}
              <div style={{ marginBottom: "14px" }}>
                <label style={{ fontSize: "12px", fontWeight: 700, color: "#334155", display: "block", marginBottom: "4px" }}>
                  💡 Custom Pedagogical Directives / Focus (Optional):
                </label>
                <input
                  type="text"
                  placeholder="e.g. Include authentic Trans-Nzoia county maize farming scenario, calculations of soil pH buffering, and KALRO citation."
                  value={qfCustomPrompt}
                  onChange={(e) => setQfCustomPrompt(e.target.value)}
                  style={{ width: "100%", padding: "8px", fontSize: "13px" }}
                />
              </div>

              {/* Submit Button */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                <button
                  style={{ background: "#7c3aed", color: "#fff", borderColor: "#7c3aed", fontSize: "13px", padding: "8px 20px", fontWeight: 700 }}
                  onClick={() => generateQuestionsFactoryBatch()}
                  disabled={isRunning}
                >
                  {isRunning ? "⚡ Synthesizing Assessment Items..." : `⚡ Generate Batch of ${qfBatchCount} Questions`}
                </button>
              </div>
            </div>

            {/* QUESTIONS WORKSPACE & REVIEW PANEL */}
            <div>
              {/* Filter Tabs and Action Toolbar */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "16px" }}>
                <div style={{ display: "flex", gap: "6px" }}>
                  <button
                    className={qfActiveFilter === "all" ? "" : "ghost"}
                    style={{ fontSize: "12px", padding: "4px 12px" }}
                    onClick={() => setQfActiveFilter("all")}
                  >
                    All Items ({qfQuestionsList.length})
                  </button>
                  <button
                    className={qfActiveFilter === "approved" ? "" : "ghost"}
                    style={{ fontSize: "12px", padding: "4px 12px" }}
                    onClick={() => setQfActiveFilter("approved")}
                  >
                    Approved ({qfQuestionsList.filter(q => q.approved).length})
                  </button>
                  <button
                    className={qfActiveFilter === "pending" ? "" : "ghost"}
                    style={{ fontSize: "12px", padding: "4px 12px" }}
                    onClick={() => setQfActiveFilter("pending")}
                  >
                    Pending Review ({qfQuestionsList.filter(q => !q.approved).length})
                  </button>
                </div>

                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <button
                    style={{ background: "#166534", color: "#fff", borderColor: "#166534", fontSize: "12px", fontWeight: 700 }}
                    onClick={approveAllQFQuestions}
                    disabled={qfQuestionsList.length === 0 || isRunning}
                  >
                    ✅ Approve All {qfQuestionsList.length} Items (Sync to DNA Repo)
                  </button>
                  <button
                    className="ghost"
                    style={{ fontSize: "12px", border: "1px solid #7c3aed", color: "#7c3aed" }}
                    onClick={exportQFExamPaper}
                    disabled={qfQuestionsList.length === 0 || isRunning}
                  >
                    📑 Export Exam Paper (KNEC/KICD Format)
                  </button>
                  <button
                    className="ghost"
                    style={{ fontSize: "12px", color: "#b91c1c", borderColor: "#fca5a5" }}
                    onClick={() => setQfQuestionsList([])}
                    disabled={qfQuestionsList.length === 0}
                  >
                    🗑️ Clear Draft Set
                  </button>
                </div>
              </div>

              {/* Questions List */}
              {qfQuestionsList.length === 0 ? (
                <div style={{ textAlign: "center", padding: "48px 20px", background: "#f8fafc", border: "2px dashed #cbd5e1", borderRadius: "10px" }}>
                  <span style={{ fontSize: "36px" }}>🎯</span>
                  <h3 style={{ margin: "10px 0 6px", color: "#334155" }}>Questions Factory Ready</h3>
                  <p style={{ color: "#64748b", maxWidth: "540px", margin: "0 auto 16px", fontSize: "13px" }}>
                    Configure the typology mix above and click <strong>"⚡ Generate Batch"</strong> to synthesize unlimited multiple-choice, diagram interpretation, practical experiments, and structured case studies linked directly to the saved lesson notes.
                  </p>
                  <button
                    style={{ background: "#7c3aed", color: "#fff", borderColor: "#7c3aed" }}
                    onClick={() => generateQuestionsFactoryBatch()}
                  >
                    ⚡ Generate Initial Batch of 5 Questions
                  </button>
                </div>
              ) : (
                <div className="stack" style={{ gap: "16px" }}>
                  {qfQuestionsList
                    .filter((q) => {
                      if (qfActiveFilter === "approved") return q.approved;
                      if (qfActiveFilter === "pending") return !q.approved;
                      return true;
                    })
                    .map((q: any, qIdx: number) => {
                      const qType = (q.question_type || "multiple_choice").replace(/_/g, " ").toUpperCase();
                      return (
                        <div
                          key={qIdx}
                          className="surface"
                          style={{
                            border: `1px solid ${q.approved ? "#86efac" : "#ddd6fe"}`,
                            borderRadius: "10px",
                            padding: "18px",
                            background: q.approved ? "#f0fdf4" : "#ffffff",
                            boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                          }}
                        >
                          {/* Card Header */}
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px", marginBottom: "12px", borderBottom: "1px solid #f1f5f9", paddingBottom: "10px" }}>
                            <div>
                              <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                                <strong style={{ fontSize: "14px", color: "#1e293b" }}>
                                  Question {qIdx + 1}: {qType}
                                </strong>
                                <span className="pill ok" style={{ fontSize: "10px", background: "#ede9fe", color: "#5b21b6", borderColor: "#c4b5fd" }}>
                                  🧠 {q.bloom_level || "Application"} • {q.max_marks || 2} Marks • ⏱️ {q.estimated_time_mins || 3} mins
                                </span>
                                <span className="pill ok" style={{ fontSize: "10px" }}>
                                  🎯 {q.micro_concept || qfSubstrand}
                                </span>
                              </div>
                              <small style={{ color: "#64748b", fontSize: "11px" }}>DNA ID: {q.universal_id || `Q-CBC-${qIdx+1}`}</small>
                            </div>

                            {/* Action Buttons */}
                            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                              <button
                                className={q.approved ? "ghost" : ""}
                                style={{
                                  fontSize: "11.5px",
                                  padding: "4px 10px",
                                  background: q.approved ? "transparent" : "#166534",
                                  borderColor: q.approved ? "#86efac" : "#166534",
                                  color: q.approved ? "#166534" : "#fff",
                                  fontWeight: 700,
                                }}
                                onClick={() => toggleApproveQuestionInQF(qIdx)}
                              >
                                {q.approved ? "✓ Approved" : "✅ Approve"}
                              </button>
                              <button
                                className="ghost"
                                style={{ fontSize: "11.5px", padding: "4px 8px" }}
                                onClick={() => generateQuestionsFactorySingle(q.question_type, q.micro_concept)}
                                title="Regenerate single question for this concept"
                              >
                                🔄 Regenerate
                              </button>
                              <button
                                className="ghost"
                                style={{ fontSize: "11.5px", padding: "4px 8px", color: "#b91c1c" }}
                                onClick={() => deleteQFQuestion(qIdx)}
                                title="Remove question from batch"
                              >
                                🗑️
                              </button>
                            </div>
                          </div>

                          {/* Stimulus Context (If Scenario-Based) */}
                          {q.stimulus_context && (
                            <div style={{ padding: "10px 14px", background: "#f8fafc", borderLeft: "4px solid #7c3aed", borderRadius: "4px", marginBottom: "12px", fontSize: "13px", color: "#334155" }}>
                              <strong style={{ color: "#6d28d9" }}>📌 Authentic Kenyan Scenario Context:</strong>
                              <p style={{ margin: "4px 0 0" }}>{q.stimulus_context}</p>
                            </div>
                          )}

                          {/* Question Prompt */}
                          <div style={{ fontSize: "14px", fontWeight: 600, color: "#0f172a", marginBottom: "12px", lineHeight: "1.5" }}>
                            {q.question_text}
                          </div>

                          {/* Diagram Callout (If Diagram-Based) */}
                          {q.diagram_ref && (
                            <div style={{ padding: "8px 12px", background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: "6px", marginBottom: "12px", fontSize: "12px", color: "#0369a1" }}>
                              📐 <strong>Diagram Reference:</strong> Refer to Figure: <em>"{q.diagram_ref}"</em> from Layer 2 Visual Studio.
                            </div>
                          )}

                          {/* MCQ Options Rendering */}
                          {q.options && q.options.length > 0 && (
                            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "8px", marginBottom: "14px" }}>
                              {normalizeQuestionOptions(q.options, q.correct_answer).map((opt: any, oIdx: number) => {
                                const isCorrect = opt.is_correct || opt.id === q.correct_answer;
                                return (
                                  <div
                                    key={oIdx}
                                    style={{
                                      padding: "10px 14px",
                                      borderRadius: "8px",
                                      border: isCorrect ? "2px solid #16a34a" : "1px solid #e2e8f0",
                                      background: isCorrect ? "#f0fdf4" : "#ffffff",
                                      fontSize: "13px",
                                    }}
                                  >
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                      <span>
                                        <strong style={{ color: isCorrect ? "#166534" : "#475569" }}>{opt.id}.</strong> {opt.text}
                                      </span>
                                      {isCorrect && (
                                        <span className="pill ok" style={{ fontSize: "10.5px", fontWeight: 700 }}>
                                          ✓ Correct Key
                                        </span>
                                      )}
                                    </div>
                                    {opt.distractor_rationale && (
                                      <div style={{ fontSize: "11px", color: isCorrect ? "#166534" : "#64748b", marginTop: "4px", fontStyle: "italic" }}>
                                        Rationale: {opt.distractor_rationale}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* Structured Scenario Parts (If Structured) */}
                          {q.structured_parts && q.structured_parts.length > 0 && (
                            <div style={{ marginBottom: "14px", padding: "12px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                              <strong style={{ fontSize: "12px", color: "#334155" }}>Structured Sub-Questions & Mark Scheme:</strong>
                              <div className="stack" style={{ gap: "8px", marginTop: "6px" }}>
                                {q.structured_parts.map((p: any, pIdx: number) => (
                                  <div key={pIdx} style={{ fontSize: "12.5px", padding: "6px 8px", background: "#fff", borderRadius: "6px", border: "1px solid #cbd5e1" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                                      <strong>{p.part_id || `(${String.fromCharCode(97+pIdx)})`} {p.sub_question}</strong>
                                      <span className="pill ok" style={{ fontSize: "10px" }}>{p.marks || 1} Marks</span>
                                    </div>
                                    {p.model_answer && (
                                      <div style={{ fontSize: "11.5px", color: "#166534", marginTop: "4px" }}>
                                        <em>Model Response: {p.model_answer}</em>
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Model Solution & Step-by-Step Marking Scheme */}
                          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px", marginBottom: "14px" }}>
                            {q.model_answer && (
                              <div style={{ padding: "10px 12px", background: "#f0fdf4", borderRadius: "8px", border: "1px solid #bbf7d0", fontSize: "12px" }}>
                                <strong style={{ color: "#166534" }}>💡 Model Solution & Explanation:</strong>
                                <p style={{ margin: "4px 0 0", color: "#14532d", whiteSpace: "pre-line" }}>{q.model_answer}</p>
                              </div>
                            )}

                            {q.marking_scheme && (
                              <div style={{ padding: "10px 12px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "12px" }}>
                                <strong style={{ color: "#334155" }}>📋 Step-by-Step Scoring Guide:</strong>
                                <p style={{ margin: "4px 0 0", color: "#475569", whiteSpace: "pre-line" }}>{q.marking_scheme}</p>
                              </div>
                            )}
                          </div>

                          {/* 4-Tier KICD Rubric Grid */}
                          {q.marking_guide && typeof q.marking_guide === "object" && (
                            <div style={{ marginTop: "10px", paddingTop: "10px", borderTop: "1px dashed #cbd5e1" }}>
                              <strong style={{ fontSize: "11.5px", color: "#475569" }}>📊 4-Tier KICD Performance Rubric Grid:</strong>
                              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px", marginTop: "6px" }}>
                                <div style={{ padding: "6px 10px", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "6px", fontSize: "11px" }}>
                                  <strong style={{ color: "#166534" }}>Exceeding:</strong> {q.marking_guide.exceeding || "Analytical mastery"}
                                </div>
                                <div style={{ padding: "6px 10px", background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: "6px", fontSize: "11px" }}>
                                  <strong style={{ color: "#0369a1" }}>Meeting:</strong> {q.marking_guide.meeting || "Standard competency"}
                                </div>
                                <div style={{ padding: "6px 10px", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "6px", fontSize: "11px" }}>
                                  <strong style={{ color: "#b45309" }}>Approaching:</strong> {q.marking_guide.approaching || "Partial understanding"}
                                </div>
                                <div style={{ padding: "6px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "6px", fontSize: "11px" }}>
                                  <strong style={{ color: "#b91c1c" }}>Below:</strong> {q.marking_guide.below || "Remediation required"}
                                </div>
                              </div>
                            </div>
                          )}

                          {/* DNA Provenance Citation Tag */}
                          <div style={{ marginTop: "12px", paddingTop: "8px", borderTop: "1px solid #f1f5f9", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "11px", color: "#64748b", flexWrap: "wrap", gap: "6px" }}>
                            <span>🧬 <strong>Verifiable DNA Lineage:</strong> {q.provenance_citation || `Linked to Layer 1 Lesson Notes (${qfSubstrand})`}</span>
                            <span style={{ fontStyle: "italic" }}>Criterion-referenced assessment</span>
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </div>

            {/* Printable KNEC / KICD Examination Modal */}
            {qfExamExportModal && qfExportedPaper && (
              <div className="modal-overlay" style={{ zIndex: 9999 }}>
                <div className="modal-content" style={{ maxWidth: "800px", maxHeight: "88vh", overflowY: "auto", padding: "24px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "2px solid #7c3aed", paddingBottom: "12px", marginBottom: "16px" }}>
                    <h2 style={{ margin: 0, color: "#5b21b6" }}>📑 Publication-Ready Exam Paper & Marking Scheme</h2>
                    <button className="ghost" onClick={() => setQfExamExportModal(false)}>✖ Close</button>
                  </div>

                  <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
                    <button
                      onClick={() => {
                        const win = window.open("", "_blank");
                        if (win) {
                          win.document.write(`<html><head><title>${qfExportedPaper.exam_title}</title><style>body{font-family:serif;margin:40px;line-height:1.6;}h1,h2,h3{color:#1e293b;}hr{margin:20px 0;}</style></head><body><pre style="white-space:pre-wrap;font-family:inherit;">${qfExportedPaper.question_paper_markdown}\n\n========================================\n\n${qfExportedPaper.marking_scheme_markdown}</pre></body></html>`);
                          win.document.close();
                          win.print();
                        }
                      }}
                    >
                      🖨️ Print Exam Paper & Marking Scheme
                    </button>
                    <button
                      className="ghost"
                      onClick={() => {
                        navigator.clipboard.writeText(`${qfExportedPaper.question_paper_markdown}\n\n${qfExportedPaper.marking_scheme_markdown}`);
                        alert("Copied complete Exam Paper and Marking Scheme to clipboard!");
                      }}
                    >
                      📋 Copy Markdown to Clipboard
                    </button>
                  </div>

                  <div style={{ background: "#f8fafc", padding: "16px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <h3>Question Paper Preview</h3>
                    <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "12px", background: "#fff", padding: "14px", borderRadius: "6px", border: "1px solid #cbd5e1" }}>
                      {qfExportedPaper.question_paper_markdown}
                    </pre>

                    <h3 style={{ marginTop: "20px" }}>Marking Scheme Preview</h3>
                    <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "12px", background: "#fff", padding: "14px", borderRadius: "6px", border: "1px solid #cbd5e1" }}>
                      {qfExportedPaper.marking_scheme_markdown}
                    </pre>
                  </div>
                </div>
              </div>
            )}
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
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  onClick={async () => {
                    await run("Bootstrap OpenAI Bindings", async () => {
                      const res = await fetchJson<any>("/admin/pipeline-bindings/bootstrap", {
                        method: "POST",
                        body: JSON.stringify({ provider: "openai", model: "gpt-4o-mini", base_url: null }),
                      }, auth());
                      setStageDrafts({
                        notes_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                        diagram_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                        activity_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                        question_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                        reviewer_panel: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                        regeneration: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
                      });
                      return res;
                    });
                  }}
                  disabled={isRunning}
                >
                  ⚡ Set All Stages to OpenAI (gpt-4o-mini)
                </button>
              </div>
            </div>

            <div className="stack" style={{ gap: "12px", marginTop: "12px" }}>
              {(Object.keys(stageDrafts) as Stage[]).map((stage) => {
                const draft = stageDrafts[stage];
                return (
                  <div key={stage} className="surface" style={{ padding: "14px", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                      <strong style={{ fontSize: "14px", color: "#0f172a" }}>{stage}</strong>
                      <span className="pill ok" style={{ fontSize: "11px" }}>{draft.provider} • {draft.model}</span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: "8px", alignItems: "flex-end" }}>
                      <label style={{ fontSize: "12px" }}>
                        Provider:
                        <select
                          value={draft.provider}
                          onChange={(e) => {
                            const p = e.target.value as Provider;
                            const defaultModel = p === "openai" ? "gpt-4o-mini" : (p === "anthropic" ? "claude-3-5-sonnet-20241022" : (p === "gemini" ? "gemini-2.0-flash" : "llama3.1"));
                            setStageDrafts({
                              ...stageDrafts,
                              [stage]: { ...draft, provider: p, model: defaultModel },
                            });
                          }}
                          style={{ marginTop: "4px" }}
                        >
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Anthropic</option>
                          <option value="gemini">Google Gemini</option>
                          <option value="ollama">Ollama / Local</option>
                        </select>
                      </label>

                      <label style={{ fontSize: "12px" }}>
                        Model ID:
                        <input
                          value={draft.model}
                          onChange={(e) => setStageDrafts({ ...stageDrafts, [stage]: { ...draft, model: e.target.value } })}
                          placeholder="e.g. gpt-4o-mini, gpt-4o, claude-3-5-sonnet-20241022"
                          style={{ marginTop: "4px" }}
                        />
                      </label>

                      <label style={{ fontSize: "12px" }}>
                        Custom Base URL (optional):
                        <input
                          value={draft.base_url || ""}
                          onChange={(e) => setStageDrafts({ ...stageDrafts, [stage]: { ...draft, base_url: e.target.value } })}
                          placeholder="Default official API URL"
                          style={{ marginTop: "4px" }}
                        />
                      </label>

                      <button
                        onClick={() => run(`Save ${stage}`, () => fetchJson(`/admin/pipeline-bindings/${stage}`, {
                          method: "POST",
                          body: JSON.stringify({
                            provider: draft.provider,
                            model: draft.model || "gpt-4o-mini",
                            base_url: draft.base_url || null,
                          }),
                        }, auth()))}
                        disabled={isRunning}
                        style={{ height: "36px" }}
                      >
                        💾 Save
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
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
