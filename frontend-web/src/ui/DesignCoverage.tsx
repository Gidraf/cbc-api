import React from "react";
import { Badge, ErrorNotice, LoadingBlock, Stack } from "./components";
import { useDesignCoverage, type DesignCoverageDimension } from "../lib/queries";

/**
 * What of the KICD design is NOT covered, named.
 *
 * The dashboards already here count what was produced — hours planned,
 * diagrams drawn, questions written — and a count cannot say WHICH outcome has
 * no question against it. A sub-strand reads 100% produced with three of its
 * five outcomes never assessed, because ten questions on outcome one look
 * exactly like ten spread across five.
 *
 * So nothing on this page is a total on its own. Every bar opens into the list
 * of elements behind it, and every uncovered element is named with the design's
 * own words, because "outcomes 60%" is a number and "these two outcomes have
 * no question" is a job somebody can pick up.
 */

const LABEL: Record<string, string> = {
  outcomes: "Learning outcomes",
  inquiry_questions: "Key inquiry questions",
  demand: "Demand — how hard the questions ask",
  learning_experiences: "Suggested learning experiences",
  core_competencies: "Core competencies",
  values: "Values",
  required_diagrams: "Required diagrams",
  experiments: "Experiments and practicals",
};

function tone(percent: number, status: string) {
  if (status === "not_stated") return "#6b7280";
  if (percent >= 90) return "#15803d";
  if (percent >= 60) return "#b45309";
  return "#b91c1c";
}

function Bar({ percent, status }: { percent: number; status: string }) {
  return (
    <div style={{ background: "#e5e7eb", borderRadius: 3, height: 8, width: "100%" }}>
      <div
        style={{
          width: `${status === "not_stated" ? 0 : Math.max(percent, 1)}%`,
          background: tone(percent, status),
          height: 8,
          borderRadius: 3,
        }}
      />
    </div>
  );
}

function Dimension({ dim }: { dim: DesignCoverageDimension }) {
  const [open, setOpen] = React.useState(false);
  // A dimension the design is silent about is not a gap. Showing it as 0%
  // would send somebody to write content the curriculum never asked for, and
  // the only way to raise the score would be to invent an experiment.
  if (!dim.stated) {
    return (
      <div style={{ padding: "6px 0", color: "#6b7280", fontSize: 12 }}>
        {LABEL[dim.name] || dim.name} — the design names none.{" "}
        <span style={{ opacity: 0.8 }}>{dim.note}</span>
      </div>
    );
  }
  return (
    <div style={{ padding: "8px 0", borderTop: "1px solid #f1f5f9" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          all: "unset", cursor: "pointer", display: "flex", width: "100%",
          alignItems: "center", gap: 10,
        }}
      >
        <span style={{ flex: "0 0 210px", fontSize: 13 }}>
          {LABEL[dim.name] || dim.name}
        </span>
        <span style={{ flex: 1 }}><Bar percent={dim.percent} status={dim.status} /></span>
        <span style={{ flex: "0 0 96px", textAlign: "right", fontSize: 12,
                       color: tone(dim.percent, dim.status) }}>
          {dim.covered}/{dim.total} · {dim.percent}%
        </span>
        <span style={{ flex: "0 0 14px", color: "#9ca3af" }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 8, marginLeft: 210, fontSize: 12 }}>
          {dim.note && (
            <div style={{ color: "#6b7280", marginBottom: 6 }}>{dim.note}</div>
          )}
          {dim.elements.map((el) => (
            <div key={el.ref} style={{ display: "flex", gap: 8, padding: "3px 0" }}>
              <span style={{ flex: "0 0 14px", color: el.covered ? "#15803d" : "#b91c1c" }}>
                {el.covered ? "✓" : "✗"}
              </span>
              <span style={{ flex: 1, color: el.covered ? "#374151" : "#111827" }}>
                <b style={{ opacity: 0.65 }}>{el.ref}</b> — {el.text}
                {!el.covered && el.how && (
                  <span style={{ color: "#b91c1c" }}> · needs {el.how}</span>
                )}
                {el.covered && (
                  <span style={{ color: "#6b7280" }}> · {el.count} question(s)</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function DesignCoverage({ grade, subject, strand }: {
  grade: string; subject: string; strand?: string;
}) {
  // Drafts and approvals are different products. A scope that is complete in
  // drafts and empty in approvals is a review queue, not something to sell.
  const [approvedOnly, setApprovedOnly] = React.useState(false);
  const q = useDesignCoverage({
    grade, subject, strand, status: approvedOnly ? "approved" : "",
  });

  if (q.isLoading) return <LoadingBlock label="Reading the design against what exists" />;
  if (q.error) return <ErrorNotice error={q.error} />;
  const data = q.data;
  if (!data) return null;

  return (
    <Stack gap="12px">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>KICD design coverage</h3>
        <Badge tone={data.percent >= 90 ? "ok" : data.percent >= 60 ? "warn" : "danger"}>
          {data.percent}% of the design covered
        </Badge>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          {data.sub_strands} sub-strand(s) · <b>{data.gap_count}</b> element(s)
          with nothing against them
        </span>
        <label style={{ marginLeft: "auto", fontSize: 12, display: "flex",
                        gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={approvedOnly}
                 onChange={(e) => setApprovedOnly(e.target.checked)} />
          approved questions only
        </label>
      </div>

      <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12 }}>
        <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 6 }}>
          Weakest aspect first — this is what to generate next.
        </div>
        {data.by_dimension.map((d) => (
          <div key={d.name} style={{ display: "flex", gap: 10, alignItems: "center",
                                     padding: "4px 0" }}>
            <span style={{ flex: "0 0 210px", fontSize: 13,
                           color: d.status === "not_stated" ? "#6b7280" : undefined }}>
              {LABEL[d.name] || d.name}
            </span>
            <span style={{ flex: 1 }}><Bar percent={d.percent} status={d.status} /></span>
            <span style={{ flex: "0 0 150px", textAlign: "right", fontSize: 12,
                           color: tone(d.percent, d.status) }}>
              {d.status === "not_stated"
                ? "no design states it"
                : `${d.covered}/${d.total} · ${d.percent}%`}
            </span>
          </div>
        ))}
      </div>

      {data.worst.length > 0 && (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Where the gaps are</div>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "#6b7280" }}>
                <th>Sub-strand</th><th>Strand</th><th>Questions</th>
                <th>Covered</th><th>Uncovered elements</th><th>Weakest</th>
              </tr>
            </thead>
            <tbody>
              {data.worst.map((w) => (
                <tr key={`${w.strand}/${w.sub_strand}`}
                    style={{ borderTop: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "4px 0" }}>{w.sub_strand}</td>
                  <td>{w.strand}</td>
                  <td>{w.questions}</td>
                  <td style={{ color: tone(w.percent, "partial") }}>{w.percent}%</td>
                  <td><b>{w.gaps}</b></td>
                  <td style={{ color: "#6b7280" }}>{LABEL[w.worst_dimension] || w.worst_dimension}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.detail.map((sub) => (
        <div key={`${sub.strand}/${sub.sub_strand}`}
             style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "baseline",
                        flexWrap: "wrap" }}>
            <b>{sub.sub_strand}</b>
            <span style={{ fontSize: 12, color: "#6b7280" }}>
              {sub.strand}
              {sub.lesson_hours ? ` · ${sub.lesson_hours}` : ""} ·{" "}
              {sub.questions} question(s)
            </span>
            <span style={{ marginLeft: "auto", fontSize: 12,
                           color: tone(sub.percent, "partial") }}>
              {sub.percent}% · {sub.gap_count} uncovered
            </span>
          </div>
          <div style={{ marginTop: 8 }}>
            {sub.dimensions.map((d) => <Dimension key={d.name} dim={d} />)}
          </div>
        </div>
      ))}
    </Stack>
  );
}
