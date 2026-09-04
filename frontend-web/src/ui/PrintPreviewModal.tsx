import React from "react";
import { MathBlock, MathText } from "./MathBlock";

export interface PrintPreviewModalProps {
  title: string;
  grade: string;
  subject: string;
  strand?: string;
  subStrand?: string;
  questions?: any[];
  notesModules?: any[];
  onClose: () => void;
}

export function PrintPreviewModal({
  title,
  grade,
  subject,
  strand,
  subStrand,
  questions = [],
  notesModules = [],
  onClose,
}: PrintPreviewModalProps) {
  const [audience, setAudience] = React.useState<"student" | "teacher">("student");

  const handlePrint = () => {
    window.print();
  };

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0, 0, 0, 0.65)",
        zIndex: 9999,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        padding: "20px",
      }}
    >
      <div
        style={{
          background: "#ffffff",
          borderRadius: "8px",
          width: "880px",
          maxWidth: "96vw",
          height: "90vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 20px 40px rgba(0,0,0,0.3)",
          overflow: "hidden",
        }}
      >
        {/* Top bar controls */}
        <div
          className="print-hide"
          style={{
            padding: "12px 20px",
            background: "#1e293b",
            color: "#ffffff",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontWeight: 600, fontSize: "15px" }}>🖨 Print Preview</span>
            <div style={{ display: "flex", background: "#334155", borderRadius: "6px", padding: "2px" }}>
              <button
                onClick={() => setAudience("student")}
                style={{
                  padding: "4px 12px",
                  borderRadius: "4px",
                  border: "none",
                  background: audience === "student" ? "#0B6E5F" : "transparent",
                  color: "#ffffff",
                  fontSize: "12px",
                  fontWeight: audience === "student" ? 600 : 400,
                  cursor: "pointer",
                }}
              >
                Student Copy (Questions only)
              </button>
              <button
                onClick={() => setAudience("teacher")}
                style={{
                  padding: "4px 12px",
                  borderRadius: "4px",
                  border: "none",
                  background: audience === "teacher" ? "#0B6E5F" : "transparent",
                  color: "#ffffff",
                  fontSize: "12px",
                  fontWeight: audience === "teacher" ? 600 : 400,
                  cursor: "pointer",
                }}
              >
                Teacher Copy (Marking Scheme)
              </button>
            </div>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            <button
              onClick={handlePrint}
              style={{
                padding: "6px 14px",
                background: "#0B6E5F",
                color: "#ffffff",
                border: "none",
                borderRadius: "4px",
                fontSize: "13px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Print / Save PDF
            </button>
            <button
              onClick={onClose}
              style={{
                padding: "6px 10px",
                background: "#475569",
                color: "#ffffff",
                border: "none",
                borderRadius: "4px",
                fontSize: "13px",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        </div>

        {/* A4 Paper simulation view */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "30px 40px",
            background: "#f1f5f9",
          }}
        >
          <div
            className="print-root"
            style={{
              maxWidth: "720px",
              margin: "0 auto",
              background: "#ffffff",
              padding: "40px",
              boxShadow: "0 2px 10px rgba(0,0,0,0.06)",
              minHeight: "1000px",
              color: "#111827",
              fontFamily: "Georgia, serif",
            }}
          >
            {/* Paper Header */}
            <div
              style={{
                textAlign: "center",
                borderBottom: "2px solid #111827",
                paddingBottom: "12px",
                marginBottom: "20px",
              }}
            >
              <h2 style={{ margin: "0 0 6px", fontSize: "20px", letterSpacing: "0.5px" }}>
                {title || `${subject} Assessment`}
              </h2>
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  gap: "16px",
                  fontSize: "11px",
                  textTransform: "uppercase",
                  letterSpacing: "1px",
                  color: "#4b5563",
                  fontWeight: 600,
                }}
              >
                <span>LEVEL: {grade}</span>
                <span>SUBJECT: {subject}</span>
                {strand && <span>STRAND: {strand}</span>}
                {subStrand && <span>SUB-STRAND: {subStrand}</span>}
                {audience === "teacher" && (
                  <span style={{ color: "#92400e", background: "#fef3c7", padding: "1px 6px", borderRadius: "3px" }}>
                    TEACHER COPY
                  </span>
                )}
              </div>
            </div>

            {/* Questions list */}
            {questions && questions.length > 0 ? (
              <div>
                <h3 style={{ fontSize: "14px", textTransform: "uppercase", letterSpacing: "1px", margin: "16px 0 12px" }}>
                  Questions ({questions.length})
                </h3>
                {questions.map((q, idx) => {
                  const qNum = idx + 1;
                  const qText = q.question_text || q.text || "";
                  const marks = q.max_marks || q.marks || 1;
                  const solTrace = q.solution_trace || {};
                  const steps = solTrace.steps || [];
                  const markingScheme = q.marking_scheme || q.marking_guide || "";

                  return (
                    <div
                      key={idx}
                      style={{
                        marginBottom: "22px",
                        pageBreakInside: "avoid",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          borderBottom: "1px solid #e5e7eb",
                          paddingBottom: "4px",
                          marginBottom: "8px",
                          fontWeight: "bold",
                          fontSize: "13px",
                        }}
                      >
                        <span>Question {qNum}</span>
                        <span style={{ fontStyle: "italic", fontSize: "12px" }}>({marks} marks)</span>
                      </div>

                      <div style={{ fontSize: "14px", lineHeight: "1.6", marginBottom: "10px" }}>
                        <MathText text={qText} />
                      </div>

                      {/* Student view: answer lines */}
                      {audience === "student" ? (
                        <div>
                          {Array.from({ length: Math.max(2, marks * 2) }).map((_, lIdx) => (
                            <div
                              key={lIdx}
                              style={{
                                borderBottom: "1px dotted #9ca3af",
                                height: "24px",
                              }}
                            />
                          ))}
                        </div>
                      ) : (
                        /* Teacher view: worked steps and marking scheme */
                        <div
                          style={{
                            background: "#f0fdf4",
                            borderLeft: "3px solid #0B6E5F",
                            padding: "8px 12px",
                            fontSize: "12px",
                            lineHeight: "1.5",
                          }}
                        >
                          <strong style={{ color: "#064e3b" }}>Worked Solution:</strong>
                          {steps.length > 0 ? (
                            <ol style={{ margin: "4px 0", paddingLeft: "20px" }}>
                              {steps.map((st: any, sIdx: number) => (
                                <li key={sIdx} style={{ margin: "4px 0" }}>
                                  <MathBlock latex={st.latex} />
                                  {st.explanation && <span style={{ marginLeft: "8px", color: "#374151" }}>({st.explanation})</span>}
                                </li>
                              ))}
                            </ol>
                          ) : (
                            <div style={{ marginTop: "4px" }}>
                              <MathText text={q.model_answer || q.correct_answer || "See criteria"} />
                            </div>
                          )}
                          {markingScheme && (
                            <div style={{ marginTop: "6px", color: "#166534" }}>
                              <strong>Marking Criteria:</strong> {markingScheme}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "40px", color: "#6b7280" }}>
                No questions generated for this sub-strand yet.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
