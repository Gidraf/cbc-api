/**
 * Data access for the console.
 *
 * Every read goes through a query key so it can be invalidated from one place.
 * The previous console called `loadDatasetProgress` manually from eight
 * different handlers because there was nothing to invalidate.
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJson } from "../api";
import { useAuth } from "./auth";

export function useApi() {
  const { token } = useAuth();
  return React.useCallback(
    <T,>(path: string, init?: RequestInit) => fetchJson<T>(path, init, { bearerToken: token }),
    [token]
  );
}

export const keys = {
  grades: ["grades"] as const,
  subjects: (grade: string) => ["subjects", grade] as const,
  substrands: (grade: string, subject: string) => ["substrands", grade, subject] as const,
  progress: (grade: string, subject?: string) => ["progress", grade, subject ?? "all"] as const,
  structure: (grade: string, subject: string) => ["structure", grade, subject] as const,
  media: (grade: string, subject: string, subStrand: string) =>
    ["media", grade, subject, subStrand] as const,
  artifacts: (filters: Record<string, unknown>) => ["artifacts", filters] as const,
  artifact: (id: string) => ["artifact", id] as const,
  artifactVersions: (key: string) => ["artifact-versions", key] as const,
  reviewVendors: (generator: string) => ["review-vendors", generator] as const,
  bundle: (grade: string, subject: string, subStrand: string) =>
    ["bundle", grade, subject, subStrand] as const,
  questions: (filters: Record<string, unknown>) => ["questions", filters] as const,
  question: (id: string) => ["question", id] as const,
  diagram: (id: string) => ["diagram", id] as const,
  exams: (filters: Record<string, unknown>) => ["exams", filters] as const,
  exam: (id: string) => ["exam", id] as const,
  costs: ["costs"] as const,
  targets: ["targets"] as const,
};

/* ── Curriculum ─────────────────────────────────────────────────────────── */

export type GradeInfo = {
  name: string;
  slug: string;
  label: string;
  level: string;
  ordinal: number;
  /** Curriculum designs ingested so far. Absent on older API builds. */
  design_count?: number;
  /** How many KICD publishes for this grade. */
  expected_design_count?: number;
  has_data?: boolean;
};

/** Label a grade option, showing ingest progress once the API reports it. */
export function gradeOptionLabel(g: GradeInfo): string {
  const label = g.label || g.name;
  if (g.design_count === undefined || g.expected_design_count === undefined) return label;
  if (g.expected_design_count === 0) return label;
  return `${label} — ${g.design_count}/${g.expected_design_count}`;
}

export function useGrades() {
  const api = useApi();
  return useQuery({
    queryKey: keys.grades,
    queryFn: async () => {
      const res = await api<{ datasets?: GradeInfo[] } | GradeInfo[]>("/api/v1/admin/langfuse/datasets");
      const list = Array.isArray(res) ? res : res.datasets || [];
      // The API already orders by the CBC ordinal; sort again defensively so a
      // stale deployment cannot reintroduce lexicographic order in the UI.
      return [...list].sort((a, b) => (a.ordinal ?? 999) - (b.ordinal ?? 999));
    },
    staleTime: 5 * 60_000,
  });
}

export type SubjectInfo = {
  name: string;
  code?: string;
  essence_statement?: string;
  /** KICD publishes a design for this subject at this grade. */
  expected?: boolean;
  /** A design has actually been ingested. Absent on older API builds. */
  ingested?: boolean;
};

/** Mark subjects KICD publishes but nothing has been ingested for yet. */
export function subjectOptionLabel(s: SubjectInfo): string {
  return s.ingested === false ? `${s.name} (not ingested)` : s.name;
}

export function useSubjects(grade: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.subjects(grade),
    queryFn: () =>
      api<{ subjects: SubjectInfo[] }>(
        `/api/v1/admin/langfuse/datasets/${grade}/subjects`
      ).then((r) => r.subjects || []),
    enabled: Boolean(grade),
    staleTime: 5 * 60_000,
  });
}

export type CoverageDimension = {
  generated_count?: number;
  generated_hours?: number;
  required_count?: number;
  required_hours?: number;
  remaining_count?: number;
  remaining_hours?: number;
  percentage: number;
  estimated?: boolean;
};

export type SubstrandReport = {
  sub_strand_name: string;
  allocated_hours: string;
  weight_hours: number;
  estimated: boolean;
  notes: CoverageDimension & { hour_modules?: any[] };
  visuals: CoverageDimension;
  practicals: CoverageDimension;
  questions: CoverageDimension;
  slo_coverage: CoverageDimension;
  overall_percentage: number;
  production_ready: boolean;
  approved: boolean;
  bundle_id: string | null;
};

export type ProgressReport = {
  grade: string;
  // Everything below is optional because the API does not always send it, and
  // typing it as required is what put the literal text "undefined" on screen.
  grade_label?: string;
  overall_grade_percentage?: number;
  rollup_method?: string;
  weights?: Record<string, number>;
  total_substrands?: number;
  completed_substrands?: number;
  production_ready_substrands?: number;
  measurement_confidence: {
    substrands_with_estimated_requirements: number;
    substrands_measured_from_blueprint: number;
    note: string;
  };
  notes_totals: CoverageDimension;
  visuals_totals: CoverageDimension;
  practicals_totals: CoverageDimension;
  questions_totals: CoverageDimension;
  slo_coverage_totals: CoverageDimension;
  // Optional on purpose: the API omits these on some payloads, and typing them
  // as required is what let three screens crash on `.length` of undefined.
  focus_recommendations?: {
    type: string;
    priority: string;
    action: string;
    subject: string;
    strand: string;
    sub_strand: string;
    percentage: number;
    message: string;
    remaining?: number;
    estimated_requirement?: boolean;
  }[];
  subjects?: {
    subject: string;
    subject_percentage: number;
    total_substrands: number;
    completed_substrands: number;
    estimated: boolean;
    strands: {
      strand_name: string;
      strand_percentage: number;
      substrands: SubstrandReport[];
    }[];
  }[];
};

export function useProgress(grade: string, subject?: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.progress(grade, subject),
    queryFn: () => {
      const qs = subject ? `?subject=${encodeURIComponent(subject)}` : "";
      return api<ProgressReport>(`/api/v1/admin/langfuse/datasets/${grade}/progress${qs}`);
    },
    enabled: Boolean(grade),
    staleTime: 30_000,
  });
}

/** Something the generator produced that was refused before it could save —
 *  raw page debris, a duplicate, an entry naming its strand instead of itself. */
export type Refusal = { strand_name?: string; sub_strand_name?: string; reason: string };

export type StoredStructure = {
  grade: string;
  subject: string;
  design_id: string;
  strand_count: number;
  sub_strand_count: number;
  strands: {
    strand_id: string;
    strand_name: string;
    description: string;
    saved: boolean;
    sub_strands: GeneratedSubstrand[];
  }[];
};

/** What is actually stored for this learning area, as opposed to what this
 *  browser tab happens to have generated. */
export function useStoredStructure(grade: string, subject: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.structure(grade, subject),
    queryFn: () =>
      api<StoredStructure>(
        `/api/v1/curriculum/factory/structure?grade=${encodeURIComponent(grade)}` +
          `&subject=${encodeURIComponent(subject)}`
      ),
    enabled: Boolean(grade && subject),
  });
}

export type MediaItem = {
  media_id: string;
  kind: "photo" | "video";
  title: string;
  purpose: string;
  generation_prompt: string;
  negative_prompt: string;
  shot_list: { shot: number; seconds: number; on_screen: string; narration: string }[];
  spec: Record<string, unknown>;
  alt_text: string;
  narration: string;
  storage_url: string;
  content_type: string;
  source_pages: number[];
  status: "planned" | "produced" | "rejected";
};

/** Photographs and videos planned for a sub-strand, with what has been produced.
 *  Unlike a diagram these are not generated as code — the factory authors the
 *  prompt and the shot list, and the asset is uploaded back against it. */
export function useSubstrandMedia(grade: string, subject: string, subStrand: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.media(grade, subject, subStrand),
    queryFn: () =>
      api<{ media: MediaItem[]; planned: number; produced: number }>(
        `/api/v1/curriculum/factory/media?grade=${encodeURIComponent(grade)}` +
          `&subject=${encodeURIComponent(subject)}&sub_strand=${encodeURIComponent(subStrand)}`
      ),
    enabled: Boolean(grade && subject && subStrand),
  });
}

/** Upload the produced photograph or video against its plan. The plan is kept:
 *  what the asset was meant to show is how a reviewer judges what arrived. */
export function useUploadMedia(grade: string, subject: string, subStrand: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { media_id: string; file: File }) => {
      const form = new FormData();
      form.append("media_id", v.media_id);
      form.append("file", v.file);
      return api<{ storage_url: string; bytes: number }>(
        "/api/v1/curriculum/factory/media/upload",
        { method: "POST", body: form }
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.media(grade, subject, subStrand) });
    },
  });
}

/* ── Artifact versions, labels and layered review ───────────────────────── */

export const ARTIFACT_KINDS = [
  "ingest", "strand", "sub_strand", "notes", "hour_module", "diagram",
  "photo_prompt", "video_prompt", "experiment", "activity", "question", "answer",
] as const;

export const ARTIFACT_LABELS = [
  "approved", "production", "staging", "test", "dev", "rejected",
] as const;

export type ArtifactLabel = (typeof ARTIFACT_LABELS)[number];

/** One dimension of a review. They fail independently: content can be exactly
 *  aligned with the design and pitched at the wrong age. */
export type DimensionScore = {
  name: string;
  score: number;
  evidence: string;
  issues: string[];
  not_applicable: boolean;
};

export type ReviewVerdict = {
  review_id: string;
  artifact_id: string;
  layer: 1 | 2 | 3;
  layer_name: string;
  provider: string;
  model: string;
  verdict: "pass" | "revise" | "reject";
  overall_confidence: number;
  dimensions: Record<string, DimensionScore>;
  issues: { severity: string; where: string; what: string; fix: string }[];
  comments: string[];
  compared_with: string;
  weakest: string;
};

export type ApprovalState = {
  can_approve: boolean;
  blockers: string[];
  layers_run: number[];
  vendors: string[];
  reviews: { layer: number; verdict: string; confidence: number; provider: string; model: string }[];
};

export type ArtifactVersion = {
  artifact_id: string;
  version: number;
  status: string;
  labels: string[];
  created_by: string;
  created_at: string;
  parent_artifact_id: string;
  reviews: { layer: number; verdict: string; confidence: number; provider: string; model: string }[];
};

export function useArtifacts(filters: {
  grade?: string;
  subject?: string;
  kind?: string;
  sub_strand?: string;
  label?: string;
}) {
  const api = useApi();
  const query = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v) as [string, string][]
  ).toString();
  return useQuery({
    queryKey: keys.artifacts(filters),
    queryFn: () => api<{ artifacts: any[]; count: number }>(`/api/v1/artifacts?${query}`),
    enabled: Boolean(filters.grade || filters.subject),
  });
}

export type RevisionDirectives = {
  artifact_id: string;
  kind: string;
  regeneratable: boolean;
  directives: string;
  issues: { severity: string; where: string; what: string; fix: string; layer: number }[];
  weak_dimensions: { dimension: string; score: number; evidence: string }[];
  human_comments: string[];
};

/** What a regeneration would carry, without running one. */
export function useRevisionDirectives(artifactId: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["revision-directives", artifactId],
    queryFn: () => api<RevisionDirectives>(`/api/v1/artifacts/${artifactId}/revision-directives`),
    enabled: Boolean(artifactId),
  });
}

export function useArtifact(artifactId: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.artifact(artifactId),
    queryFn: () =>
      api<{
        artifact_id: string;
        artifact_key: string;
        kind: string;
        version: number;
        grade: string;
        subject: string;
        strand_name: string;
        sub_strand_name: string;
        provenance: Record<string, unknown>;
        content: Record<string, unknown>;
        labels: string[];
        parent_artifact_id: string;
        reviews: ReviewVerdict[];
        comments: { comment_id: string; body: string; author: string; resolved: boolean }[];
        approval: ApprovalState;
      }>(`/api/v1/artifacts/${encodeURIComponent(artifactId)}`),
    enabled: Boolean(artifactId),
  });
}

/** Every attempt at one thing, so a good version survives trying a better one. */
export function useArtifactVersions(artifactKey: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.artifactVersions(artifactKey),
    queryFn: () =>
      api<{ versions: ArtifactVersion[] }>(
        `/api/v1/artifacts/versions?artifact_key=${encodeURIComponent(artifactKey)}`
      ),
    enabled: Boolean(artifactKey),
  });
}

/** Who can review, and which vendor would be a genuine second opinion. */
export function useReviewVendors(generatorProvider = "") {
  const api = useApi();
  return useQuery({
    queryKey: keys.reviewVendors(generatorProvider),
    queryFn: () =>
      api<{
        vendors: { provider: string; label: string; models: string[]; default: string; notes: string; available: boolean }[];
        dimensions: Record<string, { weight: number; question: string }>;
        layers: Record<string, { name: string; can_approve: boolean; brief: string }>;
        suggested: { provider?: string; model?: string };
        independent_of: string[];
      }>(
        `/api/v1/artifacts/review/vendors?generator_provider=${encodeURIComponent(generatorProvider)}`
      ),
  });
}

export function useArtifactActions(artifactId: string) {
  const api = useApi();
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.artifact(artifactId) });

  return {
    review: useMutation({
      mutationFn: (v: { layer: 1 | 2 | 3; provider?: string; model?: string; compare_with?: string }) =>
        api<ReviewVerdict & { approval: ApprovalState; reviewed_a_diff: boolean }>(
          "/api/v1/artifacts/review",
          { method: "POST", body: JSON.stringify({ artifact_id: artifactId, ...v }) }
        ),
      onSuccess: refresh,
    }),
    label: useMutation({
      // `reviewed_by_me` is a person signing for the version. Coverage counts
      // approved work as taught-ready, so approval cannot be a side effect of
      // the model layers passing.
      mutationFn: (v: { label: ArtifactLabel; reviewed_by_me?: boolean; note?: string }) =>
        api<{ status: string; moved_from: string }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}/label`,
          { method: "POST", body: JSON.stringify(v) }
        ),
      onSuccess: () => {
        refresh();
        qc.invalidateQueries({ queryKey: ["progress"] });
      },
    }),
    regenerate: useMutation({
      mutationFn: (v: { extra_instructions?: string } = {}) =>
        api<{
          status: string;
          from_version: number;
          new_artifact: { artifact_id: string; version: number } | null;
          addressed: { issues: any[]; weak_dimensions: any[]; human_comments: string[] };
          directives: string;
        }>("/api/v1/artifacts/regenerate", {
          method: "POST",
          body: JSON.stringify({ artifact_id: artifactId, ...v }),
        }),
      onSuccess: () => {
        refresh();
        qc.invalidateQueries({ queryKey: ["artifacts"] });
        qc.invalidateQueries({ queryKey: ["progress"] });
      },
    }),
    comment: useMutation({
      mutationFn: (v: { body: string; dimension?: string }) =>
        api<{ comment_id: string }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}/comments`,
          { method: "POST", body: JSON.stringify(v) }
        ),
      onSuccess: refresh,
    }),
    edit: useMutation({
      mutationFn: (content: Record<string, unknown>) =>
        api<{ artifact_id: string; version: number }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}`,
          { method: "PUT", body: JSON.stringify({ content }) }
        ),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: () =>
        api<{ status: string }>(`/api/v1/artifacts/${encodeURIComponent(artifactId)}`, {
          method: "DELETE",
        }),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["artifacts"] }),
    }),
  };
}

/** What changed between two attempts — what a layer-2 review of a regeneration
 *  is actually about. */
export function useArtifactDiff(artifactId: string, against = "") {
  const api = useApi();
  return useQuery({
    queryKey: ["artifact-diff", artifactId, against],
    queryFn: () =>
      api<{
        identical: boolean;
        counts: { added: number; removed: number; changed: number };
        added: { path: string; value: string }[];
        removed: { path: string; value: string }[];
        changed: { path: string; value: string; was: string }[];
      }>(
        `/api/v1/artifacts/${encodeURIComponent(artifactId)}/diff` +
          (against ? `?against=${encodeURIComponent(against)}` : "")
      ),
    enabled: Boolean(artifactId),
  });
}

export function useBundle(grade: string, subject: string, subStrand: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.bundle(grade, subject, subStrand),
    queryFn: () =>
      api<any>(
        `/api/v1/curriculum/factory/bundle-by-substrand?grade=${encodeURIComponent(grade)}` +
          `&subject=${encodeURIComponent(subject)}&sub_strand=${encodeURIComponent(subStrand)}`
      ),
    enabled: Boolean(grade && subject && subStrand),
  });
}

/* ── Questions ──────────────────────────────────────────────────────────── */

export type QuestionFilters = {
  grade?: string;
  subject?: string;
  strand?: string;
  sub_strand?: string;
  question_type?: string;
  status?: string;
  order?: "curriculum" | "recent";
  limit?: number;
  offset?: number;
};

export function useQuestions(filters: QuestionFilters) {
  const api = useApi();
  return useQuery({
    queryKey: keys.questions(filters as Record<string, unknown>),
    queryFn: () => {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== "") params.set(k, String(v));
      });
      return api<{ total: number; items: any[]; next_offset: number | null }>(
        `/api/v1/questions?${params.toString()}`
      );
    },
    staleTime: 15_000,
  });
}

export function useQuestionActions() {
  const api = useApi();
  const qc = useQueryClient();

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["questions"] });
    qc.invalidateQueries({ queryKey: ["progress"] });
  };

  return {
    generateBatch: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<any>("/api/v1/questions/factory/generate-batch", {
          method: "POST",
          body: JSON.stringify(body),
        }),
    }),
    approveBatch: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<any>("/api/v1/questions/factory/approve-batch", {
          method: "POST",
          body: JSON.stringify(body),
        }),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<any>(`/api/v1/questions/${encodeURIComponent(id)}`, { method: "DELETE" }),
      onSuccess: invalidate,
    }),
    rereview: useMutation({
      mutationFn: (id: string) =>
        api<any>(`/api/v1/questions/${encodeURIComponent(id)}/action`, {
          method: "POST",
          body: JSON.stringify({ action: "re-review" }),
        }),
      onSuccess: invalidate,
    }),
  };
}

/* ── Diagrams ───────────────────────────────────────────────────────────── */

export type DiagramDetail = {
  diagram_id: string;
  title: string;
  grade: string;
  subject: string;
  accessibility: { alt_text: string; tactile_description: string };
  reuse_count: number;
  layers: { layer_id: string; label: string; removable: boolean }[];
  parts: { part_id: string; label: string; layer: string; assessable: boolean; bbox: number[] }[];
  regions: { region_id: string; label: string; part_ids: string[]; bbox: number[] }[];
  render_url: string;
};

export function useDiagram(diagramId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: keys.diagram(diagramId || ""),
    queryFn: () => api<DiagramDetail>(`/api/v1/public/diagrams/${encodeURIComponent(diagramId!)}`),
    enabled: Boolean(diagramId),
  });
}

/* ── Exams ──────────────────────────────────────────────────────────────── */

export function useExams(filters: { grade?: string; subject?: string }) {
  const api = useApi();
  return useQuery({
    queryKey: keys.exams(filters),
    queryFn: () => {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => v && params.set(k, String(v)));
      return api<{ total: number; items: any[] }>(`/api/v1/exams?${params.toString()}`);
    },
    staleTime: 30_000,
  });
}

export function useComposeExam() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<any>("/api/v1/exams", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exams"] }),
  });
}

/* ── Operations ─────────────────────────────────────────────────────────── */

export function useCostSummary() {
  const api = useApi();
  return useQuery({
    queryKey: keys.costs,
    queryFn: () => api<any>("/api/v1/costs/summary"),
    staleTime: 60_000,
  });
}

export function useDailyTarget() {
  const api = useApi();
  return useQuery({
    queryKey: keys.targets,
    queryFn: () => api<any>("/api/v1/targets/today"),
    staleTime: 60_000,
  });
}


// ── Dataset ingestion ───────────────────────────────────────────────────────

export type IngestStatus = "pending" | "selected" | "processing" | "ingested" | "failed";

export type DatasetItem = {
  item_id: string;
  grade: string;
  file_id: string;
  title: string;
  declared_subject: string;
  resolved_subject: string;
  design_id: string | null;
  status: IngestStatus;
  char_count: number;
  error: string;
  finished_at?: string | null;
};

export type IngestState = {
  grade: string;
  items: DatasetItem[];
  counts: Record<IngestStatus, number>;
  total: number;
  ingested_percentage: number;
  in_progress: number;
};

export function useIngestStatus(grade: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["ingest-status", grade],
    queryFn: () => api<IngestState>(`/api/v1/admin/langfuse/datasets/${grade}/ingest-status`),
    enabled: Boolean(grade),
    refetchInterval: (q) => ((q.state.data?.in_progress ?? 0) > 0 ? 2000 : false),
  });
}

export function useIngestActions(grade: string) {
  const api = useApi();
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ["ingest-status", grade] });
    qc.invalidateQueries({ queryKey: keys.grades });
    qc.invalidateQueries({ queryKey: keys.subjects(grade) });
  };

  const post = (path: string, body?: unknown) =>
    api<any>(`/api/v1/admin/langfuse/datasets/${grade}/${path}`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    });

  return {
    sync: useMutation({ mutationFn: () => post("sync"), onSuccess: done }),
    process: useMutation({
      mutationFn: (v: { item_ids: string[]; force?: boolean }) => post("process", v),
      onSuccess: done,
    }),
    retry: useMutation({
      mutationFn: (v: { item_ids?: string[] }) => post("retry", v),
      onSuccess: done,
    }),
    uningest: useMutation({
      mutationFn: (v: { item_ids: string[]; purge_generated?: boolean }) => post("uningest", v),
      onSuccess: done,
    }),
  };
}


// ── Curriculum structure (strands and sub-strands) ──────────────────────────
// These fill curriculum_substrands when a design's layout defeats the text
// parser, which is the usual case for Pre-Primary. Without them a grade can be
// ingested and still have nothing to produce against.

export type GeneratedStrand = { strand_id?: string; strand_name?: string; name?: string; description?: string };
export type GeneratedSubstrand = Record<string, any>;

export function useStructureActions(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();

  const post = <T,>(path: string, body: unknown) =>
    api<T>(`/api/v1/curriculum/factory/${path}`, { method: "POST", body: JSON.stringify(body) });

  return {
    generateStrands: useMutation({
      mutationFn: (v: {
        level?: string;
        essence_statement?: string;
        custom_instructions?: string;
        design_id?: string;
        source_material_text?: string;
      }) =>
        post<{
          strands: GeneratedStrand[];
          refused?: Refusal[];
          grounded?: boolean;
          source_chars?: number;
        }>(
          "generate-strands",
          { grade, subject, ...v }
        ),
    }),
    generateSubstrands: useMutation({
      mutationFn: (v: {
        strand_name: string;
        strand_id?: string;
        level?: string;
        essence_statement?: string;
        general_learning_outcomes?: string[];
        source_material_text?: string;
        custom_instructions?: string;
        design_id?: string;
      }) =>
        post<{ sub_strands: GeneratedSubstrand[]; refused?: Refusal[] }>(
          "generate-substrands",
          { grade, subject, ...v }
        ),
    }),
    saveStrands: useMutation({
      mutationFn: (v: { strands: GeneratedStrand[]; design_id?: string }) =>
        post<{ saved_count: number; design_id: string }>("save-strands", {
          grade,
          subject,
          ...v,
        }),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: keys.structure(grade, subject) });
      },
    }),
    saveSubstrands: useMutation({
      mutationFn: (v: {
        strand_name: string;
        strand_id?: string;
        design_id?: string;
        substrands: GeneratedSubstrand[];
      }) => post<any>("save-substrands", { grade, subject, ...v }),
      onSuccess: () => {
        // Coverage and the station list are both derived from sub-strands.
        qc.invalidateQueries({ queryKey: keys.progress(grade) });
        qc.invalidateQueries({ queryKey: keys.subjects(grade) });
        // Without this the view still showed only what this session generated,
        // so a reload looked as though the save had not happened.
        qc.invalidateQueries({ queryKey: keys.structure(grade, subject) });
      },
    }),
  };
}

// ── Bundle lifecycle ────────────────────────────────────────────────────────
// Generated content only reaches the review queue by being audited, saved and
// published. Without these the four stations produce work that goes nowhere.

export function useBundleActions(grade: string) {
  const api = useApi();
  const qc = useQueryClient();

  const post = <T,>(path: string, body: unknown) =>
    api<T>(`/api/v1/curriculum/factory/${path}`, { method: "POST", body: JSON.stringify(body) });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.progress(grade) });
    qc.invalidateQueries({ queryKey: ["bundles"] });
  };

  return {
    audit: useMutation({
      mutationFn: (v: Record<string, any>) =>
        post<{ audit: any; score: number; passed: boolean }>("audit-bundle", v),
    }),
    save: useMutation({
      mutationFn: (v: Record<string, any>) =>
        post<{ status: string; bundle_id: string; storage_url?: string }>("save-bundle", v),
      onSuccess: refresh,
    }),
    publish: useMutation({
      mutationFn: (v: Record<string, any>) => post<any>("publish-bundle", v),
      onSuccess: refresh,
    }),
  };
}


// ── Per-hour production ─────────────────────────────────────────────────────
// The curriculum hierarchy is:
//   strand -> sub-strand (with KICD allocated hours) -> one hour module per
//   hour -> the diagrams, photo prompts, video prompts, experiments and
//   activities that belong to THAT hour.
// Assets are anchored to an hour, never to the sub-strand as a whole, which is
// what the backend already models via hour_index / target_hour.

/** What a visual is rendered as. The backend calls this generation_mode. */
export type VisualMode = "svg" | "photo_spec" | "video_storyboard" | "prompt_only";

export const VISUAL_MODES: { id: VisualMode; label: string; hint: string }[] = [
  { id: "svg", label: "Vector diagram", hint: "Addressable parts, so questions can test one region" },
  { id: "photo_spec", label: "Photo prompt", hint: "A prompt for an image model — online answers only" },
  { id: "video_storyboard", label: "Video storyboard", hint: "Scene-by-scene script for a simulation" },
  { id: "prompt_only", label: "Prompt only", hint: "Just the specification, nothing rendered" },
];

export type HourModule = Record<string, any> & { hour_index?: number; hour_title?: string };

/** The hour modules inside a notes payload, however the generator labelled them. */
export function hourModulesOf(notes: any): HourModule[] {
  const mods = notes?.hour_modules ?? notes?.notes?.hour_modules ?? [];
  if (!Array.isArray(mods)) return [];
  return mods.map((m: any, i: number) => ({
    ...m,
    hour_index: m?.hour_index ?? i + 1,
    hour_title: m?.hour_title || m?.title || `Hour ${m?.hour_index ?? i + 1}`,
  }));
}

/** Items a planner returned that belong to one hour. */
export function forHour<T extends Record<string, any>>(items: T[] | undefined, hour: number): T[] {
  if (!Array.isArray(items)) return [];
  // An item with no hour is shown against every hour rather than hidden — the
  // planner not tagging it is not a reason for it to disappear.
  return items.filter((i) => {
    const h = i.hour_index ?? i.hour ?? i.target_hour;
    return h === undefined || h === null || Number(h) === hour;
  });
}

export function useHourActions(grade: string, subject: string) {
  const api = useApi();

  const post = <T,>(path: string, body: unknown) =>
    api<T>(`/api/v1/curriculum/factory/${path}`, { method: "POST", body: JSON.stringify(body) });

  return {
    /** Plan the visuals for a sub-strand from its notes; each comes back tagged with an hour. */
    planVisuals: useMutation({
      mutationFn: (v: { strand: string; sub_strand: string; notes_content: any; min_visuals?: number; custom_instructions?: string }) =>
        post<{ visuals: any[] }>("plan-visuals", { grade, subject, ...v }),
    }),
    /** Render one planned visual as a diagram, photo prompt or video storyboard. */
    renderVisual: useMutation({
      mutationFn: (v: {
        strand: string;
        sub_strand: string;
        visual_item: any;
        generation_mode: VisualMode;
        target_hour: number;
        notes_content?: any;
        construction_prompt?: string;
        custom_instructions?: string;
      }) => post<any>("generate-single-visual", { grade, subject, ...v }),
    }),
    planActivities: useMutation({
      mutationFn: (v: { strand: string; sub_strand: string; notes_content: any; diagram_info?: any; custom_instructions?: string }) =>
        post<{ activities: any[] }>("plan-activities", { grade, subject, ...v }),
    }),
    /** Work up one planned activity or experiment in full, including safety. */
    buildActivity: useMutation({
      mutationFn: (v: { strand: string; sub_strand: string; activity_item: any; target_hour?: number; notes_content?: any; custom_instructions?: string }) =>
        post<any>("generate-single-activity", { grade, subject, ...v }),
    }),
  };
}


// ── Pedagogical profiles (teaching skills) ──────────────────────────────────
// A profile is the professor/teacher skill for one subject and grade, derived
// from the KICD design. classify_content_type() looks it up by (subject, grade)
// and injects format_for_prompt() into the notes, diagram, activity and
// question prompts — so a subject with no profile generates unskilled.

export type Profile = {
  id?: number;
  subject: string;
  grade: string;
  content_type?: string;
  persona: string;
  note_style: string;
  diagram_type: string;
  activity_type: string;
  question_type: string;
  safety_focus: string;
  grade_appropriate_tone?: string;
  special_directives?: string[];
  empirical_insights?: Record<string, any>[];
  case_studies?: Record<string, string>[];
  metadata?: Record<string, any>;
};

export type CurriculumDesign = {
  design_id: string;
  subject: string;
  grade: string;
  level?: string;
  essence_statement?: string;
  general_learning_outcomes?: string[];
  substrand_count?: number;
  review_status?: string;
};

export function useProfiles(search = "", grade = "") {
  const api = useApi();
  return useQuery({
    queryKey: ["profiles", search, grade],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (search) qs.set("search", search);
      if (grade) qs.set("grade", grade);
      const suffix = qs.toString() ? `?${qs}` : "";
      return api<{ profiles: Profile[]; count: number }>(`/api/v1/curriculum/profiles${suffix}`)
        .then((r) => r.profiles || []);
    },
    staleTime: 30_000,
  });
}

export function useDesigns() {
  const api = useApi();
  return useQuery({
    queryKey: ["designs"],
    queryFn: () =>
      api<{ designs?: CurriculumDesign[] } | CurriculumDesign[]>("/api/v1/curriculum/designs")
        .then((r) => (Array.isArray(r) ? r : r.designs || [])),
    staleTime: 60_000,
  });
}

export function useProfileActions() {
  const api = useApi();
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: ["profiles"] });

  return {
    save: useMutation({
      mutationFn: (p: Profile) =>
        api<{ profile: Profile }>(
          p.id ? `/api/v1/curriculum/profiles/${p.id}` : "/api/v1/curriculum/profiles",
          { method: p.id ? "PUT" : "POST", body: JSON.stringify(p) }
        ),
      onSuccess: done,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<any>(`/api/v1/curriculum/profiles/${id}`, { method: "DELETE" }),
      onSuccess: done,
    }),
    /** Synthesise a skill for a subject and grade with no design to hand. */
    aiGenerate: useMutation({
      mutationFn: (v: {
        subject: string;
        grade?: string;
        level?: string;
        essence_statement?: string;
        general_learning_outcomes?: string[];
      }) =>
        api<{ profile: Profile }>("/api/v1/curriculum/profiles/ai-generate", {
          method: "POST",
          body: JSON.stringify(v),
        }),
      onSuccess: done,
    }),
    /** Derive the skill from an ingested KICD design and its sub-strands. */
    fromDesign: useMutation({
      mutationFn: (designId: string) =>
        api<{ profile: Profile }>(
          `/api/v1/curriculum/profiles/generate-from-design/${encodeURIComponent(designId)}`,
          { method: "POST" }
        ),
      onSuccess: done,
    }),
    /** Refine an existing skill with an instruction. */
    improve: useMutation({
      mutationFn: (v: { profile: Profile; instructions: string }) =>
        api<{ profile: Profile }>("/api/v1/curriculum/profiles/ai-improve", {
          method: "POST",
          body: JSON.stringify(v),
        }),
      onSuccess: done,
    }),
  };
}

/** The profile that will steer generation for this subject and grade, if any. */
export function profileFor(profiles: Profile[] | undefined, subject: string, grade: string) {
  if (!profiles || !subject) return undefined;
  const s = subject.trim().toLowerCase();
  const exact = profiles.find(
    (p) => p.subject?.trim().toLowerCase() === s && p.grade?.trim().toLowerCase() === grade.trim().toLowerCase()
  );
  // A profile filed against "all" grades covers every grade for that subject.
  return exact || profiles.find(
    (p) => p.subject?.trim().toLowerCase() === s && (p.grade || "all").trim().toLowerCase() === "all"
  );
}


// ── Prompt inspection ───────────────────────────────────────────────────────
// Every generator can return its compiled prompt instead of generating, so the
// inputs — document, teaching skill, prompt version — can be checked before
// tokens are spent, and improved on evidence rather than on the output alone.

export function useInspect(grade: string, subject: string) {
  const api = useApi();
  const post = (path: string, body: unknown) =>
    api<{ inspection: any }>(`/api/v1/curriculum/factory/${path}`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then((r) => r.inspection);

  return {
    strands: useMutation({
      mutationFn: (v: Record<string, any> = {}) =>
        post("generate-strands", { grade, subject, inspect: true, ...v }),
    }),
    substrands: useMutation({
      mutationFn: (v: { strand_name: string; strand_id?: string } & Record<string, any>) =>
        post("generate-substrands", { grade, subject, inspect: true, ...v }),
    }),
    notes: useMutation({
      mutationFn: (v: { strand: string; sub_strand: string } & Record<string, any>) =>
        post("generate-notes", { grade, subject, inspect: true, ...v }),
    }),
  };
}


/** Put a design's source document back on it, without re-running extraction. */
export function useAttachSource() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { design_id?: string; grade?: string; subject?: string }) =>
      api<{ attached: boolean; chars: number; design_id: string; note?: string }>(
        "/api/v1/curriculum/designs/attach-source",
        { method: "POST", body: JSON.stringify(v) }
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["designs"] }),
  });
}


// ── Reading the curriculum design by page and line ──────────────────────────
// Every line has a stable address, so generated content can cite exactly where
// it came from and a reviewer can read those lines back.

export type DocLine = { page: number; line: number; ref: string; text: string };
export type DocPageSummary = { page: number; heading: string; line_count: number };

export type DesignDocument = {
  design_id: string;
  grade: string;
  subject: string;
  code: string;
  page_count: number;
  line_count: number;
  char_count: number;
  pages: DocPageSummary[];
  page_content?: { page: number; heading: string; line_count: number; lines: DocLine[] } | null;
  search?: { query: string; hits: DocLine[] };
  reference?: { ref: string; found: boolean; lines: DocLine[] };
};

export function useDesignDocument(designId: string, page: number, query: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["design-document", designId, page, query],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (query) qs.set("q", query);
      else if (page) qs.set("page", String(page));
      const suffix = qs.toString() ? `?${qs}` : "";
      return api<DesignDocument>(
        `/api/v1/curriculum/designs/${encodeURIComponent(designId)}/document${suffix}`
      );
    },
    enabled: Boolean(designId),
    staleTime: 5 * 60_000,
  });
}
