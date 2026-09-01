/**
 * Data access for the console.
 *
 * Every read goes through a query key so it can be invalidated from one place.
 * The previous console called `loadDatasetProgress` manually from eight
 * different handlers because there was nothing to invalidate.
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchBlob, fetchJson } from "../api";
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
  /** Where sub-strands DO live, when none were found under the grade asked for.
   *  "Nothing ingested" and "filed under another grade" look identical from the
   *  coverage screen, and they are not the same problem. */
  found_under_other_grades?: { grade: string; subject: string; sub_strands: number }[];
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
  sub_strand_name?: string;
  narration_script?: string;
  /** The lesson this asset belongs to, so an image can be placed in the guide. */
  for_lesson?: string;
};

/** Photographs and videos planned for a sub-strand, with what has been produced.
 *  Unlike a diagram these are not generated as code — the factory authors the
 *  prompt and the shot list, and the asset is uploaded back against it. */
export function useSubstrandMedia(grade: string, subject: string, subStrand = "") {
  const api = useApi();
  return useQuery({
    queryKey: keys.media(grade, subject, subStrand || "all"),
    queryFn: () => {
      // Without a sub-strand this is the whole subject's library, which is how
      // the media screen shows a learning area's images at once.
      const qs = new URLSearchParams({ grade, subject });
      if (subStrand) qs.set("sub_strand", subStrand);
      return api<{ media: MediaItem[]; planned: number; produced: number }>(
        `/api/v1/curriculum/factory/media?${qs}`
      );
    },
    enabled: Boolean(grade && subject),
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

export type ShapeFinding = {
  path: string;
  problem: "missing" | "added" | "type_changed" | "emptied";
  detail: string;
  was: string;
  now: string;
};

export type ShapeReport = {
  clean: boolean;
  /** Nothing broken. Additions are the operator's business. */
  safe: boolean;
  missing: ShapeFinding[];
  type_changed: ShapeFinding[];
  emptied: ShapeFinding[];
  added: ShapeFinding[];
  summary: string;
};

export type ApprovalState = {
  can_approve: boolean;
  /** The approver asked for revision. A person may approve over that, with a
   *  reason recorded against the version. */
  requires_override?: boolean;
  blockers: string[];
  warnings?: string[];
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
      mutationFn: (v: {
        label: ArtifactLabel;
        reviewed_by_me?: boolean;
        note?: string;
        /** Why this version is fit to teach despite the approver asking for
         *  revision. Required only when there is something to overrule. */
        override_reason?: string;
      }) =>
        api<{ status: string; moved_from: string }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}/label`,
          { method: "POST", body: JSON.stringify(v) }
        ),
      onSuccess: () => {
        refresh();
        qc.invalidateQueries({ queryKey: ["progress"] });
      },
    }),
    unlabel: useMutation({
      // A label pinned to the wrong version is worse than no label: `approved`
      // means a person signed for THAT version, and nothing else could move it.
      mutationFn: (label: ArtifactLabel) =>
        api<{ status: string }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}/label/${encodeURIComponent(label)}`,
          { method: "DELETE" }
        ),
      onSuccess: () => {
        refresh();
        qc.invalidateQueries({ queryKey: ["progress"] });
      },
    }),
    /** Review it, fix what the review found, review it again — until it meets
     *  the target or stops improving. "pass at 83%" with four open findings
     *  was being read as finished, because one number was doing the work of
     *  two: "not broken" and "stop working on it" are different bars. */
    refine: useMutation({
      mutationFn: (v: {
        provider?: string;
        model?: string;
        overall_target?: number;
        dimension_target?: number;
        max_cycles?: number;
      } = {}) =>
        api<{
          best_artifact_id: string;
          best_overall: number;
          met_target: boolean;
          stopped_because: string;
          cycles_run: number;
          target: { overall: number; dimension: number };
          outstanding: { severity: string; where: string; what: string; fix: string }[];
          cycles: {
            cycle: number; artifact_id: string; version: number; overall: number;
            weakest: string; weakest_score: number; verdict: string;
            open_issues: any[]; regenerated_to: string; error: string;
          }[];
          approval: ApprovalState;
        }>("/api/v1/artifacts/refine", {
          method: "POST",
          body: JSON.stringify({ artifact_id: artifactId, ...v }),
        }),
      onSuccess: () => {
        refresh();
        qc.invalidateQueries({ queryKey: ["artifacts"] });
        qc.invalidateQueries({ queryKey: ["artifact-versions"] });
        qc.invalidateQueries({ queryKey: ["progress"] });
      },
    }),
    /** Compare a pasted version against the one it was copied from, before
     *  filing it. A model asked to improve a guide returns the right guide
     *  with `exposition_segments` renamed to `segments` and `citations`
     *  dropped from three modules — each reads as fine to a person scanning
     *  the prose, and each breaks something downstream. */
    checkShape: useMutation({
      mutationFn: (content: Record<string, unknown>) =>
        api<ShapeReport & { from_version: number }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}/check-shape`,
          { method: "POST", body: JSON.stringify({ content }) }
        ),
    }),
    /** Throw a draft away. Refused server-side while a label points at it, so
     *  nothing silently loses its approved copy. */
    discard: useMutation({
      mutationFn: () =>
        api<{ status: string; artifact_id: string }>(
          `/api/v1/artifacts/${encodeURIComponent(artifactId)}`,
          { method: "DELETE" }
        ),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ["artifacts"] });
        qc.invalidateQueries({ queryKey: ["artifact-versions"] });
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

/** Sub-strands as they are actually stored, independent of the coverage report.
 *
 *  The factory picked its sub-strand out of the coverage report, so a grade
 *  whose coverage came back empty had no selectable sub-strand — and therefore
 *  no stations at all. Notes and media were unreachable even though the
 *  sub-strands were sitting in the database. */
export function useSavedSubstrands(grade: string, subject?: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["saved-substrands", grade, subject ?? "all"],
    queryFn: () => {
      const qs = new URLSearchParams({ grade });
      if (subject) qs.set("subject", subject);
      return api<{ substrands: any[] }>(`/api/v1/curriculum/substrands?${qs}`).then(
        (r) => r.substrands || []
      );
    },
    enabled: Boolean(grade),
    staleTime: 30_000,
  });
}

export type ResetReport = {
  scope: { grade?: string; subject?: string };
  dry_run: boolean;
  total_rows: number;
  tables: { table: string; what: string; rows: number; deleted?: boolean }[];
  skipped: { table: string; why: string }[];
  failed: { table: string; error: string }[];
  protected: string[];
  confirmation_required: string;
  message: string;
};

/** Clear generated content so the pipeline can be run again from the dataset.
 *
 *  A dry run unless `confirm` carries the exact phrase, so the counts can be
 *  read before anything goes. The Langfuse dataset is never touched: everything
 *  cleared here is derived from it and can be produced again. */
export function useFactoryReset() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { grade?: string; subject?: string; confirm?: string }) =>
      api<ResetReport>("/api/v1/curriculum/factory/reset", {
        method: "POST",
        body: JSON.stringify(v),
      }),
    onSuccess: (report) => {
      if (report.dry_run) return;
      // Everything on screen was derived from what just went.
      qc.invalidateQueries();
    },
  });
}

export type QueueStatus = {
  worker_running: boolean;
  /** Where the work actually runs: "celery", "in_process", or "nothing". */
  runs_on?: string;
  counts: Record<string, number>;
  /** "notes:done", "review:queued" — so each kind can report its own progress. */
  counts_by_kind?: Record<string, number>;
  /** How many jobs are waiting across the whole queue, not only this scope. */
  queue_depth?: number;
  total: number;
  finished: number;
  percentage: number;
  now_running: {
    kind: string; subject: string; strand: string; sub_strand: string;
    /** What the station is doing right now, written to the row as it works. */
    progress?: { elapsed_s: number; steps: { at: number; step: string; detail: string; status: string }[] };
  } | null;
  jobs: {
    job_id: string; batch_id: string; kind: string; subject: string;
    strand: string; sub_strand: string; status: string; attempts: number; error: string;
    /** Place in the line. "Queued" with no number is indistinguishable from
     *  "stuck", and an operator who queued a grade wants to know whether
     *  theirs is next or fortieth. */
    position?: number;
    /** Which step of the chain, for a pipeline job. */
    step?: string;
    /** The build that produced a failure. If it differs from the running
     *  build, the failure predates the code now deployed. */
    failed_under_build?: string;
  }[];
};

/** The chain, in the order the work depends on itself. */
export const PIPELINE_STEPS = [
  "ingest", "strands", "substrands", "notes",
  "diagram", "media", "simulation", "activity", "questions",
] as const;

export const STEP_LABEL: Record<string, string> = {
  ingest: "Read the design",
  strands: "Strands",
  substrands: "Sub-strands",
  notes: "Lesson plan",
  material: "Lesson material",
  diagram: "Diagrams",
  media: "Photos & videos",
  simulation: "Simulations",
  activity: "Activities & experiments",
  questions: "Questions",
};

/** Queue a learning area end to end: design in, questions out.
 *
 *  The chain used to be a person — ingest, wait, click strands, wait, click
 *  each strand's sub-strands, wait — an afternoon per learning area, which is
 *  the only reason the work was ever done one item at a time. */
export function useQueuePipeline(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      steps?: string[];
      strand?: string;
      custom_instructions?: string;
      force_ingest?: boolean;
    }) =>
      api<{ batch_id: string; queued: number; steps: string[]; starting_step: string }>(
        "/api/v1/curriculum/factory/queue-pipeline",
        { method: "POST", body: JSON.stringify({ grade, subject, ...v }) }
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
}

/** Regenerate reviewed versions from their findings, in the background. */
export function useQueueRegenerate(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { artifact_ids?: string[]; extra_instructions?: string }) =>
      api<{ batch_id: string; queued: number; artifacts: number }>(
        "/api/v1/curriculum/factory/queue-regenerate",
        { method: "POST", body: JSON.stringify({ grade, subject, ...v }) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
  });
}

/** Send artifacts for review or for the approver's work, in the background.
 *
 *  The reviewers and the approver are model calls like the generators, and were
 *  the half of the pipeline still run by hand one artifact at a time. This
 *  queues the approver's WORK — the approval itself stays a person's decision. */
export function useQueueReview(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      work: "review" | "approval";
      strand?: string;
      artifact_ids?: string[];
      kinds?: string[];
      layer?: number;
    }) =>
      api<{ batch_id: string; queued: number; artifacts: number; work: string }>(
        "/api/v1/curriculum/factory/queue-review",
        { method: "POST", body: JSON.stringify({ grade, subject, ...v }) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
  });
}

export const QUEUEABLE_KINDS = [
  "notes", "diagram", "media", "simulation", "activity", "questions",
] as const;

/** Which queue kind each production station runs as.
 *
 *  The stations used to generate on the HTTP request that asked for them, so a
 *  refresh, a navigation or a proxy timeout lost a run that was minutes in and
 *  had already been paid for. */
export const STATION_KIND: Record<string, string> = {
  notes: "notes",
  material: "material",
  visuals: "diagram",
  media: "media",
  simulations: "simulation",
  practicals: "activity",
  questions: "questions",
};

export type QueuedJob = {
  job_id: string;
  kind: string;
  grade: string;
  subject: string;
  strand: string;
  sub_strand: string;
  status: string;
  attempts: number;
  error: string;
  result: any;
  finished_at?: string;
};

/** One job and what it produced. Polled while it runs, read once when it lands.
 *
 *  The result is stored, so reopening the console after a refresh shows the
 *  finished output rather than a green tick and no way back to it. */
export function useQueuedJob(jobId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ["queued-job", jobId ?? ""],
    queryFn: () =>
      api<QueuedJob>(`/api/v1/curriculum/factory/queue/job/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const data = query.state.data as QueuedJob | undefined;
      if (!data) return 2000;
      // Faster while it is actually working, because this poll also carries the
      // step-by-step progress the worker writes to the row: at three seconds a
      // live run reads as a stalled one. A queued job has nothing to say yet.
      if (data.status === "running") return 1500;
      return data.status === "queued" ? 3000 : false;
    },
  });
}

/** Queue stations across many sub-strands. The request returns immediately;
 *  progress is read from the queue. */
export function useQueueWork(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { kinds: string[]; strand?: string; sub_strands?: string[];
                      custom_instructions?: string }) =>
      api<{ batch_id: string; queued: number; sub_strands: number }>(
        "/api/v1/curriculum/factory/queue",
        { method: "POST", body: JSON.stringify({ grade, subject, ...v }) }
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
}

/** Poll while work is outstanding, and stop when it is not — a screen that
 *  polls an idle queue forever is a request every few seconds, all day. */
export function useQueueStatus(grade: string, subject?: string, batchId?: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["queue", grade, subject ?? "all", batchId ?? ""],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (batchId) qs.set("batch_id", batchId);
      if (grade) qs.set("grade", grade);
      if (subject) qs.set("subject", subject);
      return api<QueueStatus>(`/api/v1/curriculum/factory/queue/status?${qs}`);
    },
    enabled: Boolean(grade),
    refetchInterval: (query) => {
      const data = query.state.data as QueueStatus | undefined;
      if (!data) return 4000;
      const outstanding = (data.counts.queued ?? 0) + (data.counts.running ?? 0);
      return outstanding > 0 ? 4000 : false;
    },
  });
}

/** A strand's sub-strands, generated and waiting for somebody to accept them.
 *
 *  Drafts live server-side on purpose. Held in the console they were lost to
 *  every re-render: generate all five strands, save one, and the other four
 *  went with the component that was holding them. */
export type SubstrandDraft = {
  job_id: string;
  batch_id: string;
  strand_name: string;
  strand_id: string;
  sub_strands: GeneratedSubstrand[];
  refused?: Refusal[];
  grounded?: boolean;
  source_chars?: number;
  model?: string;
  finished_at?: string;
  /** Produced by an older generator than the one running now. */
  stale?: boolean;
  /** What that older generator was missing, in one sentence. */
  missing?: string;
  generator?: string;
};

/** Queue sub-strand generation for several strands at once, one at a time. */
export function useQueueSubstrands(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      strands?: { strand_name: string; strand_id?: string }[];
      custom_instructions?: string;
    }) =>
      api<{ batch_id: string; queued: number; strands: string[] }>(
        "/api/v1/curriculum/factory/queue-substrands",
        { method: "POST", body: JSON.stringify({ grade, subject, ...v }) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["substrand-drafts"] });
    },
  });
}

/** Poll for finished drafts while anything is still outstanding. */
export function useSubstrandDrafts(grade: string, subject: string, active: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ["substrand-drafts", grade, subject],
    queryFn: () => {
      const qs = new URLSearchParams({ grade, subject, kind: "substrands" });
      return api<{
        count: number;
        stale: number;
        generator: string;
        drafts: SubstrandDraft[];
      }>(`/api/v1/curriculum/factory/queue/drafts?${qs}`);
    },
    enabled: Boolean(grade && subject),
    // Only while the queue has work in flight. Polling an idle queue is a
    // request every few seconds, all day, for nothing.
    refetchInterval: active ? 4000 : false,
  });
}

export type DeleteReport = {
  scope: Record<string, string>;
  dry_run: boolean;
  total_rows: number;
  tables: { table: string; what: string; rows: number }[];
  strand_removed_from_design: boolean;
  confirmation_required: string;
  message: string;
  queued?: number;
};

/** Remove ONE strand or ONE sub-strand, with everything generated from it.
 *
 *  The factory reset clears a whole learning area — right for "the pipeline
 *  changed, start again", wrong for "this one came out badly". With only the
 *  reset, you either keep a bad sub-strand or lose eleven good ones with it. */
export function useDeleteScope(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { strand?: string; sub_strand?: string; confirm?: string }) =>
      api<DeleteReport>("/api/v1/curriculum/factory/delete-scope", {
        method: "POST",
        body: JSON.stringify({ grade, subject, ...v }),
      }),
    onSuccess: (report) => {
      if (report.dry_run) return;
      qc.invalidateQueries({ queryKey: keys.structure(grade, subject) });
      qc.invalidateQueries({ queryKey: ["saved-substrands"] });
      qc.invalidateQueries({ queryKey: ["progress"] });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
    },
  });
}

/** Delete a strand's sub-strands and queue them to be generated again. */
export function useRegenerateScope(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      strand: string; strand_id?: string; sub_strand?: string;
      custom_instructions?: string; confirm?: string;
    }) =>
      api<DeleteReport>("/api/v1/curriculum/factory/regenerate-scope", {
        method: "POST",
        body: JSON.stringify({ grade, subject, ...v }),
      }),
    onSuccess: (report) => {
      if (report.dry_run) return;
      qc.invalidateQueries({ queryKey: keys.structure(grade, subject) });
      qc.invalidateQueries({ queryKey: ["saved-substrands"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
      qc.invalidateQueries({ queryKey: ["substrand-drafts"] });
    },
  });
}

/** Throw away every draft an older generator produced. */
/** Download everything generated for a grade or learning area, as a zip of
 *  JSON. Fetched with the auth header rather than linked, because a plain
 *  <a href> carries no token and would download the sign-in page. */
export function useExportBundle(grade: string, subject?: string) {
  const { token } = useAuth();
  return useMutation({
    mutationFn: async () => {
      const qs = new URLSearchParams({ grade, fmt: "zip" });
      if (subject) qs.set("subject", subject);
      const { blob, filename } = await fetchBlob(
        `/api/v1/curriculum/factory/export?${qs}`,
        { bearerToken: token }
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return filename;
    },
  });
}

/** One filed guide as a PDF a teacher can carry.
 *
 *  Fetched with the auth header and turned into a blob rather than linked: a
 *  plain <a href> carries no token and would download the sign-in page. */
export function useNotesPdf() {
  const { token } = useAuth();
  return useMutation({
    mutationFn: async (artifactId: string) => {
      const { blob, filename } = await fetchBlob(
        `/api/v1/curriculum/factory/notes.pdf?artifact_id=${encodeURIComponent(artifactId)}`,
        { bearerToken: token }
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "teachers-guide.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return filename;
    },
  });
}

export type AutoRunStatus = {
  running: boolean;
  run_id?: string;
  grade?: string;
  subjects?: string[];
  floor?: number;
  window?: number;
  status?: string;
  items_scored?: number;
  items_counted?: number;
  average?: number;
  recent_average?: number;
  recent_median?: number;
  halted_reason?: string;
  weakest_items?: { label: string; score: number; weakest: string }[];
  queue?: QueueStatus;
  note?: string;
};

/** Generate a grade unattended, with a floor the run stops at. */
export type StageBinding = {
  name: string;
  label: string;
  drives: string;
  guidance: string;
  falls_back_to: string;
  provider: string;
  model: string;
  base_url: string | null;
  /** Bound elsewhere and borrowed, rather than set on this stage. */
  inherited_from: string;
  configured: boolean;
};

/** Which model runs which station. */
export function useStageBindings() {
  const api = useApi();
  return useQuery({
    queryKey: ["stage-bindings"],
    queryFn: () =>
      api<{ stages: StageBinding[]; providers: string[]; note: string }>(
        "/admin/pipeline-bindings"
      ),
    staleTime: 60_000,
  });
}

export function useSetStageBinding() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { stage: string; provider: string; model: string; base_url?: string | null }) =>
      api<StageBinding>(`/admin/pipeline-bindings/${encodeURIComponent(v.stage)}`, {
        method: "POST",
        body: JSON.stringify({
          provider: v.provider, model: v.model, base_url: v.base_url ?? null,
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stage-bindings"] }),
  });
}

export function useStartAutoRun(grade: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { subjects?: string[]; floor?: number; window?: number;
                      steps?: string[]; review_cycles?: number;
                      custom_instructions?: string }) =>
      api<AutoRunStatus>("/api/v1/curriculum/factory/auto-run", {
        method: "POST",
        body: JSON.stringify({ grade, ...v }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auto-run"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

/** Poll while it runs, stop when it halts — a finished run does not change. */
export function useAutoRunStatus(grade: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["auto-run", grade],
    queryFn: () =>
      api<AutoRunStatus>(
        `/api/v1/curriculum/factory/auto-run/status?grade=${encodeURIComponent(grade)}`
      ),
    enabled: Boolean(grade),
    refetchInterval: (query) =>
      (query.state.data as AutoRunStatus | undefined)?.running ? 6000 : false,
  });
}

export type AutoRunActivity = {
  running: boolean;
  run_id?: string;
  status?: string;
  floor?: number;
  recent_median?: number;
  average?: number;
  halted_reason?: string;
  progress?: { finished: number; total: number; remaining: number; percentage: number };
  spend?: {
    cost_usd: number; tokens: number; per_item_usd: number;
    projected_remaining_usd: number;
    by_station: { kind: string; jobs: number; calls: number; tokens: number; cost: number }[];
  };
  pace?: { elapsed_seconds: number; items_per_hour: number };
  /** The run in the pipeline's own vocabulary: which stage of which subject
   *  it is on. A percentage answers "how far" and nothing about WHERE, and an
   *  operator watching a grade run overnight is asking which stage is slow. */
  stages?: {
    stage: string; label: string; total: number; queued: number;
    running: number; done: number; failed: number; cost_usd: number;
    percentage: number; status: string;
  }[];
  subjects?: {
    subject: string; total: number; done: number; failed: number;
    active: number; cost: number;
  }[];
  now_running?: {
    job_id: string; kind: string; step?: string; strand: string;
    sub_strand: string; subject: string; seconds: number; attempts: number;
    progress?: { elapsed_s: number; steps: { at: number; step: string; detail: string; status: string }[] };
  }[];
  recent?: {
    job_id: string; kind: string; step?: string; strand: string; sub_strand: string;
    subject: string; status: string; score?: string; weakest?: string;
    cycles?: string; cost_usd?: number; total_tokens?: number; error?: string;
    finished_at?: string;
  }[];
  note?: string;
};

/** What the run is doing, producing and spending — polled while it runs. */
export function useAutoRunActivity(grade: string, running: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ["auto-run-activity", grade],
    queryFn: () =>
      api<AutoRunActivity>(
        `/api/v1/curriculum/factory/auto-run/activity?grade=${encodeURIComponent(grade)}`
      ),
    enabled: Boolean(grade),
    // Fast while it moves, once when it stops. A finished run does not change.
    // Two seconds while it moves: the step log is what makes this worth
    // watching, and at four it reads as a stalled run.
    refetchInterval: running ? 2000 : false,
  });
}

export function useStopAutoRun() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      api<{ cancelled_jobs: number }>(
        `/api/v1/curriculum/factory/auto-run/stop?run_id=${encodeURIComponent(runId)}`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auto-run"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

export function useDiscardStaleDrafts(grade: string, subject: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => {
      const qs = new URLSearchParams({ grade, subject });
      return api<{ discarded: number; strands: string[] }>(
        `/api/v1/curriculum/factory/queue/discard-stale-drafts?${qs}`,
        { method: "POST" }
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["substrand-drafts"] }),
  });
}

export function useDiscardDraft() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { job_id: string }) =>
      api<{ discarded: number }>(
        "/api/v1/curriculum/factory/queue/discard-draft",
        { method: "POST", body: JSON.stringify(v) }
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["substrand-drafts"] }),
  });
}

/** Put failed work back in the queue, by hand.
 *
 *  A job that crashed twice is parked rather than retried automatically, but
 *  "parked" was a dead end: a job that failed on a bug since fixed stayed
 *  failed for ever with no way to move it. */
export type ServerHealth = {
  status: string;
  generator: string;
  started_at: string;
  worker: { celery: string; in_process: boolean };
};

/** What code the API is actually running, and since when.
 *
 *  Two rounds went on a bug that was already fixed, because a stale process and
 *  a live fix were indistinguishable from the console. */
export function useServerHealth() {
  const api = useApi();
  return useQuery({
    queryKey: ["server-health"],
    queryFn: () => api<ServerHealth>("/health"),
    refetchInterval: 30_000,
  });
}

export function useRetryFailed(grade: string, subject?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { job_id?: string } = {}) => {
      const qs = new URLSearchParams();
      if (v.job_id) qs.set("job_id", v.job_id);
      else {
        qs.set("grade", grade);
        if (subject) qs.set("subject", subject);
      }
      return api<{ retried: number; note: string }>(
        `/api/v1/curriculum/factory/queue/retry?${qs}`, { method: "POST" }
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useCancelQueue() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { batch_id?: string; job_id?: string }) => {
      const qs = new URLSearchParams(
        Object.entries(v).filter(([, x]) => x) as [string, string][]
      );
      return api<{ cancelled: number }>(
        `/api/v1/curriculum/factory/queue/cancel?${qs}`, { method: "POST" }
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
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
        post<{
          sub_strands: GeneratedSubstrand[];
          refused?: Refusal[];
          rubric_tables?: { rows: number; complete_rows: number; pages_read: number[];
                            attached: number; unmatched_indicators: string[] };
          rubric_integrity?: {
            checked: number; sound: boolean;
            errors: { check: string; sub_strand: string; level: string; message: string }[];
            design_defects: { check: string; sub_strand: string; message: string }[];
          };
          source_pages_resolved?: number;
        }>(
          "generate-substrands",
          { grade, subject, ...v }
        ),
    }),
    saveStrands: useMutation({
      mutationFn: (v: { strands: GeneratedStrand[]; design_id?: string }) =>
        post<{
          saved_count: number;
          design_id: string;
          /** Strands whose stored sub-strands no longer match any name this
           *  run produced — a rename orphans the work under the old name. */
          orphaned_strands?: string[];
        }>("save-strands", {
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
        // And without THIS the sub-strand picker never saw the sub-strands that
        // had just been saved, so the production stations stayed unreachable
        // until a hard reload — the stations are keyed on a selected sub-strand,
        // and there was nothing to select.
        qc.invalidateQueries({ queryKey: ["saved-substrands"] });
        // The save marked the queued draft consumed server-side. Without this
        // the strand keeps offering the draft it was just used to write.
        qc.invalidateQueries({ queryKey: ["substrand-drafts"] });
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


// ── The pipeline board ───────────────────────────────────────────────────────
// A grade is a project, a subject is a branch of it, and each stage is a build
// step with its own gate. Everything needed to answer "where is this grade?"
// existed and was spread across five screens.

export type StagePolicy = {
  stage: string;
  required_layers: number[];
  min_vendors: number;
  overall_target: number;
  dimension_target: number;
  requires_human: boolean;
  blocks_downstream: boolean;
  max_refine_cycles: number;
  updated_by: string;
  why: string;
};

export type BoardStage = {
  stage: string;
  label: string;
  status: string;
  expected: number;
  built: number;
  reviewed: number;
  approved: number;
  running: number;
  failed: number;
  percentage: number;
  cost_usd: number;
  last_run: string;
  blocked_by: string;
  policy: StagePolicy;
  /** Only on `ingest`: where the design came from, and whether it arrived. */
  dataset?: {
    state: "not_imported" | "imported" | "running" | "failing" | "done";
    note: string;
    designs: number;
    items: number;
    by_status: Record<string, number>;
  };
};

export type BoardBranch = {
  subject: string;
  status: string;
  blocking_stage: string;
  blocked_by: string;
  cost_usd: number;
  stages: BoardStage[];
};

export type BoardProject = {
  grade: string;
  label: string;
  branches: number;
  by_status: Record<string, number>;
  cost_usd: number;
  subjects: BoardBranch[];
};

export type BoardRun = {
  job_id: string;
  kind: string;
  subject: string;
  strand: string;
  sub_strand: string;
  status: string;
  attempts: number;
  error: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  llm_calls: number;
  total_tokens: number;
  cost_usd: number;
  progress?: { elapsed_s: number; steps: { at: number; step: string; detail: string; status: string }[] };
};

/** What a stage's jobs did, newest first, with the steps each one wrote. A
 *  stage that says "2 failed" and cannot say what failed is a red light with
 *  no wiring behind it. */
export function useStageLogs(grade: string, stage: string, subject: string, on: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ["stage-logs", grade, stage, subject],
    queryFn: () => {
      const qs = new URLSearchParams({ stage });
      if (subject) qs.set("subject", subject);
      return api<{
        grade: string; stage: string; subject: string;
        runs: BoardRun[];
        counts: Record<string, number>;
      }>(`/api/v1/pipelines/${encodeURIComponent(grade)}/logs?${qs}`);
    },
    enabled: on && Boolean(grade && stage),
    refetchInterval: (query) => {
      const data = query.state.data as { counts?: Record<string, number> } | undefined;
      const busy = (data?.counts?.running ?? 0) + (data?.counts?.queued ?? 0);
      return busy > 0 ? 2000 : false;
    },
  });
}

/** Start one stage from the board. It knows what is missing; it should be able
 *  to ask for it, rather than sending an operator to the factory to choose the
 *  same grade and subject again. */
export function useRunStage() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      grade: string; stage: string; subject?: string;
      sub_strands?: string[]; custom_instructions?: string;
    }) =>
      api<{ queued: number; jobs: { job_id: string }[]; stage: string }>(
        "/api/v1/pipelines/run",
        { method: "POST", body: JSON.stringify(v) }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      qc.invalidateQueries({ queryKey: ["stage-logs"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

export type PromptFragment = {
  name: string;
  langfuse_name: string;
  title: string;
  subjects: string[];
  stations: string[];
  grades: string[];
  from_ordinal: number;
  to_ordinal: number;
  why: string;
  /** What in the KICD design this serves — domain knowledge is exactly where a
   *  prompt drifts away from the curriculum and towards what the author
   *  happens to know about the subject. */
  kicd: string;
  chars: number;
  body: string;
  applies_here?: boolean;
};

/** The domain prompts, and where each applies. */
export function usePromptFragments(subject = "", grade = "", station = "") {
  const api = useApi();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["prompt-fragments", subject, grade, station],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (subject) qs.set("subject", subject);
      if (grade) qs.set("grade", grade);
      if (station) qs.set("station", station);
      return api<{ fragments: PromptFragment[] }>(
        `/api/v1/pipelines/fragments${qs.toString() ? `?${qs}` : ""}`
      );
    },
  });
  return {
    list,
    save: useMutation({
      mutationFn: (v: { name: string; body: string }) =>
        api<{ fragment: PromptFragment; saved: boolean }>(
          `/api/v1/pipelines/fragments/${encodeURIComponent(v.name)}`,
          { method: "PUT", body: JSON.stringify({ body: v.body }) }
        ),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["prompt-fragments"] }),
    }),
  };
}

export type StageUnit = {
  artifact_id: string;
  artifact_key: string;
  version: number;
  status: string;
  subject: string;
  strand_name: string;
  sub_strand_name: string;
  layers_run: number[];
  verdict: string;
  confidence: number;
  can_approve: boolean;
  requires_override: boolean;
  blockers: string[];
  warnings: string[];
};

/** The individual versions at one stage, and what each still needs. A stage
 *  that says "5 of 7 not reviewed" and cannot say WHICH five leaves a person to
 *  go and find them, which is the work the board was supposed to remove. */
export function useStageUnits(grade: string, stage: string, subject: string, on: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ["stage-units", grade, stage, subject],
    queryFn: () => {
      const qs = new URLSearchParams({ stage });
      if (subject) qs.set("subject", subject);
      return api<{ grade: string; stage: string; kind: string; units: StageUnit[]; note?: string }>(
        `/api/v1/pipelines/${encodeURIComponent(grade)}/units?${qs}`
      );
    },
    enabled: on && Boolean(grade && stage),
  });
}

export type AssetRequirement = {
  kind: string;
  what: string;
  module_number: number;
  module_title: string;
  topic: string;
  source: string;
  station: string;
};

/** What the lesson plans ask for, per lesson, in their own words.
 *
 *  The plan already names its assets. Nothing was reading them: each asset
 *  station was given the sub-strand's title and outcomes and asked to plan from
 *  scratch, so an asset the plan asked for was never guaranteed to exist. */
export function useStageRequirements(
  grade: string,
  subject: string,
  station: string,
  on: boolean
) {
  const api = useApi();
  return useQuery({
    queryKey: ["stage-requirements", grade, subject, station],
    queryFn: () => {
      const qs = new URLSearchParams({ subject });
      if (station) qs.set("station", station);
      return api<{
        plans_read: number;
        total: number;
        to_generate: number;
        by_kind: Record<string, number>;
        by_station: Record<string, number>;
        items: AssetRequirement[];
      }>(`/api/v1/pipelines/${encodeURIComponent(grade)}/requirements?${qs}`);
    },
    enabled: on && Boolean(grade && subject),
  });
}

/** Throw away one stage's output, or a grade's, so it can be built again.
 *
 *  A stage-level reset because that is the unit an operator works in: clearing
 *  a whole grade to re-run the diagrams costs the lesson plans that were fine. */
export function useResetPipeline() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { grade: string; stage?: string; subject?: string; confirm?: string }) =>
      api<{
        stage: string;
        supported: boolean;
        dry_run?: boolean;
        versions?: number;
        jobs?: number;
        total?: number;
        message: string;
      }>("/api/v1/pipelines/reset", { method: "POST", body: JSON.stringify(v) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      qc.invalidateQueries({ queryKey: ["stage-units"] });
      qc.invalidateQueries({ queryKey: ["stage-logs"] });
      qc.invalidateQueries({ queryKey: ["artifacts"] });
      qc.invalidateQueries({ queryKey: ["progress"] });
    },
  });
}

/** Run, review, send for approval, or regenerate — from the board.
 *
 *  Every one of these already existed, on a different screen, asking for the
 *  same grade and subject again. */
export function useStageAction() {
  const api = useApi();
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["pipeline"] });
    qc.invalidateQueries({ queryKey: ["pipelines"] });
    qc.invalidateQueries({ queryKey: ["stage-logs"] });
    qc.invalidateQueries({ queryKey: ["stage-units"] });
    qc.invalidateQueries({ queryKey: ["queue"] });
  };
  return {
    act: useMutation({
      mutationFn: (v: {
        grade: string; stage: string; subject?: string;
        action: "run" | "review" | "approval" | "regenerate";
        layer?: number; provider?: string; model?: string;
      }) =>
        api<{ queued: number; stage: string; action: string }>(
          "/api/v1/pipelines/act",
          { method: "POST", body: JSON.stringify(v) }
        ),
      onSuccess: refresh,
    }),
    approve: useMutation({
      mutationFn: (v: {
        artifact_ids: string[]; reviewed_by_me: boolean;
        note?: string; override_reason?: string;
      }) =>
        api<{
          approved: string[];
          refused: { artifact_id: string; reason: string }[];
          counts: { approved: number; refused: number };
        }>("/api/v1/pipelines/approve", {
          method: "POST",
          body: JSON.stringify(v),
        }),
      onSuccess: refresh,
    }),
  };
}

/** Every grade there is, in curriculum order — not only the ingested ones. */
export function usePipelines() {
  const api = useApi();
  return useQuery({
    queryKey: ["pipelines"],
    queryFn: () =>
      api<{
        projects: {
          grade: string; label: string; level: string; ingested: boolean;
          subjects: number; sub_strands: number;
          running: number; failed: number; cost_usd: number;
        }[];
        stages: StagePolicy[];
      }>("/api/v1/pipelines"),
    // A board with work in flight is watched; an idle one is not polled all day.
    refetchInterval: (query) => {
      const data = query.state.data as { projects?: { running: number }[] } | undefined;
      return data?.projects?.some((p) => p.running > 0) ? 5000 : false;
    },
  });
}

/** One grade, stage by stage, subject by subject. */
export function usePipeline(grade: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["pipeline", grade],
    queryFn: () => api<BoardProject>(`/api/v1/pipelines/${encodeURIComponent(grade)}`),
    enabled: Boolean(grade),
    refetchInterval: (query) => {
      const data = query.state.data as BoardProject | undefined;
      const busy = data?.subjects?.some((s) =>
        s.stages.some((st) => st.running > 0)
      );
      return busy ? 5000 : false;
    },
  });
}

/** What each stage has to pass before its output moves on. */
export function useStagePolicies() {
  const api = useApi();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["stage-policies"],
    queryFn: () =>
      api<{ policies: StagePolicy[]; stages: string[] }>("/api/v1/pipelines/policies"),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["stage-policies"] });
    qc.invalidateQueries({ queryKey: ["pipeline"] });
    qc.invalidateQueries({ queryKey: ["pipelines"] });
  };
  return {
    list,
    save: useMutation({
      mutationFn: (v: { stage: string } & Partial<StagePolicy>) => {
        const { stage, ...rest } = v;
        return api<{ policy: StagePolicy }>(
          `/api/v1/pipelines/policies/${encodeURIComponent(stage)}`,
          { method: "PUT", body: JSON.stringify(rest) }
        );
      },
      onSuccess: refresh,
    }),
    reset: useMutation({
      mutationFn: (stage: string) =>
        api<{ policy: StagePolicy }>(
          `/api/v1/pipelines/policies/${encodeURIComponent(stage)}`,
          { method: "DELETE" }
        ),
      onSuccess: refresh,
    }),
  };
}
