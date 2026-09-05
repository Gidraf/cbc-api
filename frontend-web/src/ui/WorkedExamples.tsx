import React from "react";
import { MathText } from "./MathBlock";

/**
 * The worked examples for one lesson, with their mathematics typeset.
 *
 * There were two renderers for this and neither worked. The studio panel
 * expected `{scenario, solution_steps}` — a shape the notes schema does not
 * produce — and the reader printed `JSON.stringify(worked_examples)`, so a
 * teacher opening the book saw the raw object. Neither typeset any LaTeX, so
 * `$\frac{2}{3}$` printed as dollars and a backslash.
 *
 * Both shapes are accepted here, because guides filed before the schema
 * changed still hold the old one and they should still read.
 */
export interface WorkedExample {
  statement?: string;
  steps?: Array<{ working?: string; because?: string } | string>;
  answer?: string;
  // The older shape, still in filed guides.
  scenario?: string;
  solution_steps?: Array<string> | string;
  explanation?: string;
  solution_explanation?: string;
  research_source?: string;
}

function normalise(raw: any): WorkedExample[] {
  if (!raw) return [];
  const list = Array.isArray(raw) ? raw : [raw];
  return list.filter((e) => e && typeof e === "object") as WorkedExample[];
}

function steps(example: WorkedExample): Array<{ working: string; because: string }> {
  if (Array.isArray(example.steps)) {
    return example.steps.map((s) =>
      typeof s === "string"
        ? { working: s, because: "" }
        : { working: s?.working || "", because: s?.because || "" }
    );
  }
  const legacy = example.solution_steps;
  if (Array.isArray(legacy)) return legacy.map((s) => ({ working: String(s), because: "" }));
  if (typeof legacy === "string" && legacy.trim())
    return [{ working: legacy, because: "" }];
  return [];
}

export function WorkedExamples({ examples, lesson }: { examples: any; lesson?: number }) {
  const list = normalise(examples);
  if (list.length === 0) return null;

  return (
    <div
      style={{
        padding: "14px",
        background: "#f8fafc",
        borderRadius: "8px",
        border: "1px solid #cbd5e1",
      }}
    >
      <strong style={{ fontSize: "13.5px", color: "#334155" }}>Worked examples</strong>
      {list.map((example, idx) => {
        const statement = example.statement || example.scenario || "";
        const why = example.explanation || example.solution_explanation || "";
        const rows = steps(example);
        return (
          <div
            key={idx}
            style={{
              fontSize: "12.5px",
              marginTop: "8px",
              padding: "10px 12px",
              background: "#fff",
              borderRadius: "6px",
              border: "1px solid #e2e8f0",
              borderLeft: "3px solid #0f172a",
            }}
          >
            <div
              style={{
                fontSize: "10.5px",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "#64748b",
                marginBottom: "4px",
              }}
            >
              Example {lesson ? `${lesson}.${idx + 1}` : idx + 1}
            </div>

            {statement && (
              <div style={{ color: "#0f172a", fontWeight: 600, lineHeight: 1.6 }}>
                <MathText text={statement} />
              </div>
            )}

            {rows.length > 0 && (
              <ol style={{ margin: "8px 0 0", paddingLeft: "18px", color: "#0f172a" }}>
                {rows.map((step, sIdx) => (
                  <li key={sIdx} style={{ marginBottom: "5px", lineHeight: 1.6 }}>
                    <MathText text={step.working} />
                    {step.because && (
                      <div style={{ color: "#64748b", fontStyle: "italic", fontSize: "11.5px" }}>
                        <MathText text={step.because} />
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}

            {example.answer && (
              <div
                style={{
                  marginTop: "8px",
                  paddingTop: "6px",
                  borderTop: "1px solid #e2e8f0",
                  color: "#0f172a",
                }}
              >
                <span
                  style={{
                    fontSize: "10.5px",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "#64748b",
                    marginRight: "8px",
                  }}
                >
                  Answer
                </span>
                <MathText text={example.answer} />
              </div>
            )}

            {why && (
              <div style={{ marginTop: "6px", color: "#475569", fontStyle: "italic" }}>
                <MathText text={why} />
              </div>
            )}

            {example.research_source && (
              <div style={{ marginTop: "4px", color: "#64748b", fontSize: "11px" }}>
                Source: {example.research_source}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
