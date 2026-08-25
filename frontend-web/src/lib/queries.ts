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

export type GradeInfo = { name: string; slug: string; label: string; level: string; ordinal: number };

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

export function useSubjects(grade: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.subjects(grade),
    queryFn: () =>
      api<{ subjects: { name: string; code?: string; essence_statement?: string }[] }>(
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
  grade_label: string;
  overall_grade_percentage: number;
  rollup_method: string;
  weights: Record<string, number>;
  total_substrands: number;
  completed_substrands: number;
  production_ready_substrands: number;
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
  focus_recommendations: {
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
  subjects: {
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
