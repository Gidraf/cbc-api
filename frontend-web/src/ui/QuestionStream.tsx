import React from "react";
import { Badge, Button, Stack } from "./components";
import { useAuth } from "../lib/auth";

/**
 * Questions appearing as they are produced.
 *
 * Not token streaming: a batch is one JSON object, so streaming its tokens
 * would show a reviewer half-written braces. The useful unit is a finished,
 * structure-checked question, so the run arrives in small instalments and each
 * item is listed the moment it lands.
 *
 * `EventSource` cannot carry an Authorization header, so this reads the stream
 * with `fetch` and parses the SSE frames itself. That also means the run can be
 * stopped: aborting the fetch ends the generation rather than leaving it
 * spending money into a page nobody is watching.
 */
type Item = { n: number; question: any };

export function QuestionStream({
  grade,
  subject,
  strand,
  subStrand,
}: {
  grade: string;
  subject: string;
  strand: string;
  subStrand: string;
}) {
  const { token } = useAuth();
  const [items, setItems] = React.useState<Item[]>([]);
  const [target, setTarget] = React.useState(0);
  const [running, setRunning] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [count, setCount] = React.useState(20);
  const abort = React.useRef<AbortController | null>(null);

  // A run left going when the operator navigates away is a run nobody will
  // read, still being paid for.
  React.useEffect(() => () => abort.current?.abort(), []);

  async function start() {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setItems([]);
    setNote("");
    setRunning(true);

    const qs = new URLSearchParams({
      grade, subject, strand, sub_strand: subStrand,
      batch_count: String(count),
    });
    try {
      const res = await fetch(
        `/api/v1/questions/factory/generate-stream?${qs}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        }
      );
      if (!res.ok || !res.body) {
        setNote(`The stream did not start (${res.status}).`);
        setRunning(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line; a partial frame stays in
        // the buffer until the rest of it arrives.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          let event = "";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7);
            else if (line.startsWith("data: ")) data = line.slice(6);
          }
          if (!data) continue;
          const payload = JSON.parse(data);
          if (event === "start") setTarget(payload.target);
          else if (event === "question") setItems((was) => [...was, payload]);
          else if (event === "error") setNote(payload.reason);
          else if (event === "done") setNote(`${payload.produced} produced.`);
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") setNote(String(err?.message || err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Watch them arrive</strong>
        <input
          type="number"
          min={1}
          max={500}
          value={count}
          onChange={(e) => setCount(Number(e.target.value) || 1)}
          disabled={running}
          style={{
            width: 78, padding: "4px 7px", borderRadius: "var(--radius-sm)",
            border: "1px solid var(--line)", background: "var(--surface-2)",
            color: "var(--ink-1)",
          }}
        />
        {running ? (
          <Button size="sm" variant="danger" onClick={() => abort.current?.abort()}>
            Stop
          </Button>
        ) : (
          <Button size="sm" onClick={start}>Start</Button>
        )}
        {(running || items.length > 0) && (
          <Badge tone={items.length >= target && target > 0 ? "ok" : "warn"}>
            {items.length}{target ? ` of ${target}` : ""}
          </Badge>
        )}
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Each one is saved as it lands — stopping keeps what has arrived.
        </span>
      </Stack>

      {note && (
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{note}</div>
      )}

      {items.map(({ n, question }) => (
        <div
          key={question.question_id || n}
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--s2) var(--s3)",
          }}
        >
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "baseline", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "var(--text-sm)" }}>Q{n}</strong>
            <Badge tone="neutral">{question.question_type || "—"}</Badge>
            {question?.pedagogy?.max_marks ? (
              <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
                {question.pedagogy.max_marks} mark
                {question.pedagogy.max_marks === 1 ? "" : "s"}
              </span>
            ) : null}
          </Stack>
          <div style={{ marginTop: 4, fontSize: "var(--text-sm)" }}>
            {question.question_text}
          </div>
          {Array.isArray(question.options) && question.options.length > 0 && (
            <ul style={{ margin: "var(--s1) 0 0", paddingLeft: "1.2rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {question.options.map((o: any, i: number) => (
                <li key={o?.id || i}>
                  <b>{o?.id}</b> {o?.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Stack>
  );
}
