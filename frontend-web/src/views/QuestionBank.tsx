import React from "react";
import { useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Input,
  LoadingBlock,
  Modal,
  QueryState,
  PageHeader,
  Select,
  Stack,
  Table,
  Td,
  Th,
  useToast,
} from "../ui/components";
import { useGrades, useQuestionActions, useQuestions, useSubjects } from "../lib/queries";
import { useComposeExam } from "../lib/queries";

const PAGE_SIZE = 25;

export function QuestionBank() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const grades = useGrades();

  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  const status = params.get("status") || "approved";
  const order = (params.get("order") as "curriculum" | "recent") || "curriculum";
  const page = Number(params.get("page") || 0);

  const subjects = useSubjects(grade);
  const questions = useQuestions({
    grade: grade || undefined,
    subject: subject || undefined,
    status: status || undefined,
    order,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const actions = useQuestionActions();
  const composeExam = useComposeExam();

  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [preview, setPreview] = React.useState<any | null>(null);
  const [composing, setComposing] = React.useState(false);

  function setParam(patch: Record<string, string>) {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  }

  const items = questions.data?.items || [];

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function compose(title: string, timeAllowed: string) {
    const ids = items.filter((q) => selected.has(q.question_id)).map((q) => q.question_id);
    if (!ids.length) return;
    const first = items.find((q) => selected.has(q.question_id));
    const cl = first?.curriculum_link || {};
    try {
      const res = await composeExam.mutateAsync({
        title,
        grade: cl.grade || grade,
        subject: cl.subject || subject,
        strand: cl.strand || "",
        sub_strand: cl.sub_strand || "",
        time_allowed: timeAllowed,
        question_ids: ids,
      });
      toast(`Exam composed with ${ids.length} questions (${res.total_marks} marks).`, "ok");
      setSelected(new Set());
      setComposing(false);
      window.open(`/api/v1/exams/${res.exam_id}/render?format=html&include_answers=true`, "_blank");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not compose the exam.", "danger");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Assess"
        title="Question bank"
        description="Every stored item, ordered along the CBC progression from PP1 upward rather than newest-first. Select items to compose a paper."
        actions={
          <>
            <Select aria-label="Grade" value={grade} onChange={(e) => setParam({ grade: e.target.value, subject: "" })} style={{ width: "auto" }}>
              <option value="">All grades</option>
              {(grades.data || []).map((g) => (
                <option key={g.slug || g.name} value={g.slug || g.name}>
                  {g.label || g.name}
                </option>
              ))}
            </Select>
            <Select aria-label="Subject" value={subject} onChange={(e) => setParam({ subject: e.target.value })} style={{ width: "auto" }}>
              <option value="">All subjects</option>
              {(subjects.data || []).map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </Select>
            <Select aria-label="Status" value={status} onChange={(e) => setParam({ status: e.target.value })} style={{ width: "auto" }}>
              <option value="approved">Approved</option>
              <option value="needs_review">Needs review</option>
              <option value="">Any status</option>
            </Select>
            <Select aria-label="Order" value={order} onChange={(e) => setParam({ order: e.target.value })} style={{ width: "auto" }}>
              <option value="curriculum">Curriculum order</option>
              <option value="recent">Newest first</option>
            </Select>
          </>
        }
      />

      {selected.size > 0 && (
        <Card accent="accent">
          <Stack direction="row" align="center" justify="space-between" wrap gap="var(--s3)">
            <span style={{ fontSize: "var(--text-sm)" }}>
              <strong>{selected.size}</strong> question{selected.size === 1 ? "" : "s"} selected
            </span>
            <Stack direction="row" gap="var(--s2)">
              <Button size="sm" onClick={() => setSelected(new Set())}>Clear</Button>
              <Button size="sm" variant="primary" onClick={() => setComposing(true)}>
                Compose exam
              </Button>
            </Stack>
          </Stack>
        </Card>
      )}

      <QueryState query={questions} label="Loading questions" rows={6} />

      {questions.data && items.length === 0 && (
        <EmptyState
          title="No questions match these filters"
          description="Generate a batch from the content factory, or widen the filters above."
        />
      )}

      {items.length > 0 && (
        <Card padded={false}>
          <Table caption="Question bank">
            <thead>
              <tr>
                <Th />
                <Th>Question</Th>
                <Th>Grade</Th>
                <Th>Subject</Th>
                <Th>Type</Th>
                <Th numeric>Marks</Th>
                <Th numeric>Quality</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {items.map((q) => {
                const cl = q.curriculum_link || {};
                const ped = q.pedagogical_dna || {};
                const content = q.content || {};
                const mean = q.review_audit?.mean_score;
                return (
                  <tr key={q.question_id}>
                    <Td>
                      <input
                        type="checkbox"
                        checked={selected.has(q.question_id)}
                        onChange={() => toggle(q.question_id)}
                        aria-label={`Select ${content.question_text?.slice(0, 40) || q.question_id}`}
                      />
                    </Td>
                    <Td>
                      <button
                        onClick={() => setPreview(q)}
                        style={{
                          background: "none",
                          border: "none",
                          padding: 0,
                          textAlign: "left",
                          cursor: "pointer",
                          color: "var(--ink)",
                          fontWeight: 550,
                          maxWidth: "30rem",
                        }}
                      >
                        {content.question_text?.slice(0, 110) || "(no text)"}
                        {content.question_text?.length > 110 ? "…" : ""}
                      </button>
                      <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                        {cl.sub_strand} · {cl.slo_id || "no SLO"}
                        {q.version > 1 && ` · v${q.version}`}
                      </div>
                    </Td>
                    <Td>{cl.grade}</Td>
                    <Td>{cl.subject}</Td>
                    <Td>
                      <Badge tone="neutral">{(content.question_type || "").replace(/_/g, " ")}</Badge>
                    </Td>
                    <Td numeric>{ped.max_marks ?? "—"}</Td>
                    <Td numeric>
                      {mean == null ? (
                        <span style={{ color: "var(--ink-3)" }}>—</span>
                      ) : (
                        <Badge tone={mean >= 0.75 ? "ok" : mean >= 0.55 ? "warn" : "danger"}>
                          {Math.round(mean * 100)}
                        </Badge>
                      )}
                    </Td>
                    <Td>
                      <Stack direction="row" gap="var(--s1)">
                        <Button size="sm" variant="ghost" onClick={() => actions.rereview.mutate(q.question_id)}>
                          Re-score
                        </Button>
                      </Stack>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>

          <Stack direction="row" justify="space-between" align="center" style={{ padding: "var(--s3) var(--s4)" }}>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              Showing {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + items.length}
            </span>
            <Stack direction="row" gap="var(--s2)">
              <Button size="sm" disabled={page === 0} onClick={() => setParam({ page: String(page - 1) })}>
                Previous
              </Button>
              <Button
                size="sm"
                disabled={!questions.data?.next_offset}
                onClick={() => setParam({ page: String(page + 1) })}
              >
                Next
              </Button>
            </Stack>
          </Stack>
        </Card>
      )}

      <QuestionPreview question={preview} onClose={() => setPreview(null)} />
      <ComposeDialog open={composing} count={selected.size} onClose={() => setComposing(false)} onCompose={compose} busy={composeExam.isPending} />
    </>
  );
}

function QuestionPreview({ question, onClose }: { question: any | null; onClose: () => void }) {
  if (!question) return null;
  const content = question.content || {};
  const audit = question.review_audit || {};
  const scores: Record<string, number | null> = audit.scores || {};
  const detail: Record<string, any> = audit.score_detail || {};

  return (
    <Modal open onClose={onClose} title="Question detail">
      <Stack gap="var(--s4)">
        {content.stimulus_context && (
          <p style={{ background: "var(--surface-2)", padding: "var(--s3)", borderRadius: "var(--radius-sm)", fontSize: "var(--text-sm)" }}>
            {content.stimulus_context}
          </p>
        )}
        <p style={{ fontWeight: 550 }}>{content.question_text}</p>

        {Array.isArray(content.options) && content.options.length > 0 && (
          <ol style={{ margin: 0, paddingLeft: "1.4rem" }}>
            {content.options.map((o: any) => (
              <li key={o.id} style={{ marginBottom: "var(--s2)", color: o.is_correct ? "var(--ok)" : "var(--ink)" }}>
                <strong>{o.id}.</strong> {o.text}
                {o.is_correct && <Badge tone="ok">correct</Badge>}
                {o.distractor_rationale && (
                  <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{o.distractor_rationale}</div>
                )}
              </li>
            ))}
          </ol>
        )}

        {Array.isArray(content.structured_parts) && content.structured_parts.map((p: any) => (
          <div key={p.part_id} style={{ borderLeft: "2px solid var(--line)", paddingLeft: "var(--s3)" }}>
            <strong>{p.part_id}</strong> {p.sub_question} <em>({p.marks} marks)</em>
            {p.model_answer && (
              <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: "4px" }}>{p.model_answer}</div>
            )}
          </div>
        ))}

        {content.model_answer && (
          <Card title="Model answer" padded>
            <p style={{ fontSize: "var(--text-sm)" }}>{content.model_answer}</p>
          </Card>
        )}

        {Object.keys(scores).length > 0 && (
          <Card title="Question DNA" description="Every score names the method that produced it.">
            <Table caption="DNA scores">
              <thead>
                <tr>
                  <Th>Metric</Th>
                  <Th numeric>Score</Th>
                  <Th>Method</Th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(scores).map(([k, v]) => (
                  <tr key={k}>
                    <Td>{k.replace(/_/g, " ")}</Td>
                    <Td numeric>
                      {v == null ? <Badge tone="neutral">pending</Badge> : (v as number).toFixed(2)}
                    </Td>
                    <Td style={{ color: "var(--ink-2)", fontSize: "var(--text-xs)" }}>
                      {detail[k]?.method} — {detail[k]?.evidence}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        )}
      </Stack>
    </Modal>
  );
}

function ComposeDialog({
  open,
  count,
  onClose,
  onCompose,
  busy,
}: {
  open: boolean;
  count: number;
  onClose: () => void;
  onCompose: (title: string, time: string) => void;
  busy: boolean;
}) {
  const [title, setTitle] = React.useState("End of Term Assessment");
  const [time, setTime] = React.useState("1 hour 30 minutes");

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Compose exam"
      width="min(30rem, 94vw)"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={() => onCompose(title, time)}>
            Compose {count} question{count === 1 ? "" : "s"}
          </Button>
        </>
      }
    >
      <Stack gap="var(--s4)">
        <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Composing freezes the exact question versions in this paper, so reprinting it next term produces
          the same document even if the source questions are later revised.
        </p>
        <label style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>
          Title
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>
          Time allowed
          <Input value={time} onChange={(e) => setTime(e.target.value)} />
        </label>
      </Stack>
    </Modal>
  );
}
