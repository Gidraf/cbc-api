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
import { gradeOptionLabel, subjectOptionLabel, useGrades, useQuestionActions, useBankRecheck, useBankReview, useProviders, useQuestions, useQuestionSources, useSubjects } from "../lib/queries";
import { QueuePanel } from "./QueuePanel";
import { useComposeExam } from "../lib/queries";

const PAGE_SIZE = 25;

export function QuestionBank() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const grades = useGrades();

  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  // Every status by default: a batch is filed as `draft` the moment it is
  // generated, whichever model wrote it, and defaulting to Approved hid all
  // of it — the bank looked empty while it was holding hundreds of items.
  const status = params.get("status") || "";
  const source = params.get("source") || "";
  const order = (params.get("order") as "curriculum" | "recent") || "curriculum";
  const page = Number(params.get("page") || 0);

  const subjects = useSubjects(grade);
  const questions = useQuestions({
    grade: grade || undefined,
    subject: subject || undefined,
    status: status || undefined,
    source: source || undefined,
    order,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const actions = useQuestionActions();
  const composeExam = useComposeExam();
  const sources = useQuestionSources(grade || undefined, subject || undefined);
  const recheck = useBankRecheck();
  const review = useBankReview();
  const providers = useProviders();
  const [reviewing, setReviewing] = React.useState(false);

  function recheckBank() {
    const scope = grade ? `${grade}${subject ? ` · ${subject}` : ""}` : "the whole bank";
    const ok = window.confirm(
      `Re-check ${scope} with today's checks?\n\n` +
        "Marking schemes and stems are repaired in place, keys the engine can prove are moved, " +
        "and items that fail a check — the same task under two ids, an unexplained key, an item " +
        "below the grade — are marked Needs review with the reasons. Approved items are never demoted. " +
        "No model is called; this costs nothing."
    );
    if (ok) recheck.mutate({ grade: grade || undefined, subject: subject || undefined });
  }

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
                  {gradeOptionLabel(g)}
                </option>
              ))}
            </Select>
            <Select aria-label="Subject" value={subject} onChange={(e) => setParam({ subject: e.target.value })} style={{ width: "auto" }}>
              <option value="">All subjects</option>
              {(subjects.data || []).map((s) => (
                <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>
              ))}
            </Select>
            <Select aria-label="Status" value={status} onChange={(e) => setParam({ status: e.target.value })} style={{ width: "auto" }}>
              <option value="">Any status</option>
              <option value="draft">Draft (as generated)</option>
              <option value="approved">Approved</option>
              <option value="needs_review">Needs review</option>
            </Select>
            <Select aria-label="Written by" value={source} onChange={(e) => setParam({ source: e.target.value })} style={{ width: "auto" }}>
              <option value="">Any writer</option>
              <option value="agent">Any agent (BYOM)</option>
              {(sources.data?.sources || [])
                .filter((s) => s.provider || s.model)
                .map((s) => (
                  <option key={`${s.provider}:${s.model}`} value={s.model || s.provider}>
                    {s.label} ({s.total})
                  </option>
                ))}
            </Select>
            <Select aria-label="Order" value={order} onChange={(e) => setParam({ order: e.target.value })} style={{ width: "auto" }}>
              <option value="curriculum">Curriculum order</option>
              <option value="recent">Newest first</option>
            </Select>
            <Button size="sm" variant="secondary" disabled={recheck.isPending} onClick={recheckBank}
                    title="Run today's checks over what is already filed; repairs what needs no model, flags the rest">
              {recheck.isPending ? "Re-checking…" : "Re-check bank"}
            </Button>
            <Button size="sm" variant="primary" disabled={!grade || review.isPending} onClick={() => setReviewing(true)}
                    title={grade ? "A second model reads every item in this scope, fixes what fails, holds what still fails" : "Pick a grade first"}>
              Review with AI
            </Button>
          </>
        }
      />

      {recheck.error && <ErrorNotice error={recheck.error} />}
      {review.error && <ErrorNotice error={review.error} />}
      {review.data && (
        <div role="status"
             style={{ border: "1px solid var(--line)", background: "var(--surface-2, var(--surface))",
                      borderRadius: "var(--radius)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
          <strong>Review queued</strong> — {review.data.queued} job{review.data.queued === 1 ? "" : "s"}
          {review.data.jobs.length > 0 && <>: {review.data.jobs.map((j) => j.subject).join(", ")}</>}. {review.data.note}
        </div>
      )}
      {recheck.data && (
        <div role="status"
             style={{ border: "1px solid var(--line)", background: "var(--surface-2, var(--surface))",
                      borderRadius: "var(--radius)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
          <strong>Re-checked {recheck.data.checked} item{recheck.data.checked === 1 ? "" : "s"}</strong>
          {" — "}{recheck.data.repaired_count} repaired in place, {recheck.data.flagged_count} marked Needs review
          {recheck.data.cleared.length > 0 && <>, {recheck.data.cleared.length} cleared</>}.
          {Object.keys(recheck.data.findings_by_kind).length > 0 && (
            <div style={{ marginTop: "var(--s1)", color: "var(--ink-2)" }}>
              {Object.entries(recheck.data.findings_by_kind).map(([k, v]) => `${v} × ${k.replace(/_/g, " ")}`).join(" · ")}
            </div>
          )}
          <div style={{ marginTop: "var(--s1)", color: "var(--ink-3)" }}>
            Filter Status → Needs review to read each item's reasons; a paper composed from the bank leaves them out.
          </div>
        </div>
      )}
      {sources.data && (
        <div role="status"
             style={{ border: "1px solid var(--line)", background: "var(--surface-2, var(--surface))",
                      borderRadius: "var(--radius)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
          <strong>{sources.data.total} item{sources.data.total === 1 ? "" : "s"} in the bank</strong>
          {grade && <> for {grade}{subject ? ` · ${subject}` : ""}</>}
          {Object.keys(sources.data.by_status).length > 0 && (
            <> — {Object.entries(sources.data.by_status).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")}</>
          )}
          {sources.data.sources.length > 0 && (
            <div style={{ marginTop: "var(--s1)", color: "var(--ink-2)" }}>
              Written by:{" "}
              {sources.data.sources.map((s) => `${s.label} (${s.total})`).join(" · ")}
            </div>
          )}
          <div style={{ marginTop: "var(--s1)", color: "var(--ink-3)" }}>
            Every generation is filed here whichever model answered — a provider or an agent — and
            a paper composed from the bank spends no tokens. Orders skip any sub-strand that
            already has enough items.
          </div>
        </div>
      )}

      {/* The same queue the content factory runs on. Question generation is a
          model call like every other one and used to be held open on the
          request that asked for it, so a refresh in the middle threw away a
          batch that had already been paid for. Generated here, it runs in the
          worker, reviews itself, and is still going when you come back. */}
      {grade && subject && (
        <details style={{ marginBottom: "var(--s4)" }}>
          <summary
            style={{
              cursor: "pointer",
              fontSize: "var(--text-md)",
              fontWeight: 600,
              padding: "var(--s3)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
            }}
          >
            Generate and review in the background
          </summary>
          <div style={{ marginTop: "var(--s3)" }}>
            <QueuePanel grade={grade} subject={subject} defaultKinds={["questions"]} />
          </div>
        </details>
      )}

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
          description="Queue a batch above — it runs in the background and reviews itself — or widen the filters."
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
                <Th>Status · written by</Th>
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
                    <Td>
                      <Stack gap="2px">
                        <Badge tone={q.status === "approved" ? "ok" : q.status === "draft" ? "neutral" : "warn"}>
                          {String(q.status || "").replace(/_/g, " ")}
                        </Badge>
                        <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}
                              title={q.provenance?.agent_task ? `task ${q.provenance.agent_task}` : undefined}>
                          {q.provenance?.written_by || "—"}
                        </span>
                      </Stack>
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
      <ReviewDialog
        open={reviewing}
        scope={grade ? `${grade}${subject ? ` · ${subject}` : " · every subject"}` : ""}
        providers={(providers.data?.providers || []).filter((p) => p.has_api_key || p.provider === "ollama")}
        busy={review.isPending}
        onClose={() => setReviewing(false)}
        onReview={(v) => {
          review.mutate({ grade, subject: subject || undefined, ...v });
          setReviewing(false);
        }}
      />
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

function ReviewDialog({
  open, scope, providers, busy, onClose, onReview,
}: {
  open: boolean;
  scope: string;
  providers: { provider: string; ollama_models?: string[] | null }[];
  busy: boolean;
  onClose: () => void;
  onReview: (v: { provider?: string; model?: string; fix: boolean; approve_clean: boolean }) => void;
}) {
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const [fix, setFix] = React.useState(true);
  const [approve, setApprove] = React.useState(false);
  const hint: Record<string, string> = {
    openai: "e.g. gpt-5.6-terra", anthropic: "e.g. claude-opus-5", gemini: "e.g. gemini-2.5-pro", ollama: "e.g. qwen3:32b",
  };
  return (
    <Modal open={open} onClose={onClose} title="Review with AI" width="min(34rem, 94vw)"
           footer={<>
             <Button onClick={onClose}>Cancel</Button>
             <Button variant="primary" loading={busy}
                     onClick={() => onReview({ provider: provider || undefined, model: model || undefined, fix, approve_clean: approve })}>
               Queue review of {scope}
             </Button>
           </>}>
      <Stack gap="var(--s4)">
        <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          A second model reads every item in the scope cold: answers it, checks the key, checks that the
          story and the sum say the same thing, judges the distractors and the scheme. With <b>fix</b> on, what
          fails is rewritten and the rewrite replaces the original (an approved item is versioned); what still
          fails is held as <i>Needs review</i> with the reasons. Pick a <b>different vendor</b> from the one
          that wrote the items — the same model asked twice agrees with itself. One job per subject, on the
          queue; it spends that vendor's tokens.
        </p>
        <label style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>
          Reader
          <Select value={provider} onChange={(e) => { setProvider(e.target.value); setModel(""); }}>
            <option value="">Review binding (Model per station → Review layers)</option>
            {providers.map((p) => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
          </Select>
        </label>
        {provider && (
          <label style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>
            Model
            <Input value={model} placeholder={hint[provider] || "model name"} onChange={(e) => setModel(e.target.value)}
                   list={provider === "ollama" ? "ollama-models" : undefined} />
            {provider === "ollama" && (
              <datalist id="ollama-models">
                {(providers.find((p) => p.provider === "ollama")?.ollama_models || []).map((m) => <option key={m} value={m} />)}
              </datalist>
            )}
          </label>
        )}
        <label style={{ fontSize: "var(--text-sm)", display: "flex", gap: "var(--s2)", alignItems: "center" }}>
          <input type="checkbox" checked={fix} onChange={(e) => setFix(e.target.checked)} />
          Fix what fails (rewrite and replace); off = report and hold only
        </label>
        <label style={{ fontSize: "var(--text-sm)", display: "flex", gap: "var(--s2)", alignItems: "center" }}>
          <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} />
          Approve every item that passes (the DRAFT stamp comes off a paper when all its items are approved)
        </label>
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
