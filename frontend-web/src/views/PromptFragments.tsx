import React from "react";
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Field,
  Input,
  LoadingBlock,
  Stack,
  Textarea,
} from "../ui/components";
import {
  useExportPrompts,
  useImportPrompts,
  usePromptFragments,
  type PromptChange,
  type PromptFragment,
  type PromptImportPlan,
} from "../lib/queries";

/**
 * The domain prompts, one at a time.
 *
 * Education is wide. A prompt that must serve every subject is a prompt nobody
 * improves: change the paragraph about balancing equations and you have edited
 * the prompt that writes a PP1 singing lesson — so the person who knows
 * chemistry will not touch it, and it stays wrong.
 *
 * These are small, separate, and each is its own Langfuse prompt. Somebody who
 * knows maps can improve the map fragment without reading a word of the rest.
 */

function Fragment({ fragment }: { fragment: PromptFragment }) {
  const { save } = usePromptFragments();
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState(fragment.body);
  const changed = text !== fragment.body;

  return (
    <Card
      title={fragment.title}
      description={fragment.why}
      accent={fragment.applies_here ? "ok" : undefined}
      actions={
        <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center" }}>
          {fragment.applies_here !== undefined && (
            <Badge tone={fragment.applies_here ? "ok" : "neutral"}>
              {fragment.applies_here ? "applies here" : "not here"}
            </Badge>
          )}
          <span className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
            {fragment.langfuse_name}
          </span>
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
            {open ? "Close" : "Edit"}
          </Button>
        </Stack>
      }
    >
      <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s2)" }}>
        {fragment.subjects.map((s) => (
          <Badge key={s} tone="neutral">
            {s}
          </Badge>
        ))}
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
          {fragment.grades.length
            ? `${fragment.grades[0]} → ${fragment.grades[fragment.grades.length - 1]}`
            : "every grade"}
          {" · "}
          {fragment.stations.join(", ")}
        </span>
      </Stack>

      {/* Domain knowledge is exactly where a prompt drifts away from the
          curriculum and towards what the author happens to know about the
          subject. Naming the design's own hook is what holds it. */}
      <p
        style={{
          fontSize: "var(--text-sm)",
          color: "var(--ink-2)",
          borderLeft: "2px solid var(--accent)",
          paddingLeft: "var(--s3)",
          margin: "0 0 var(--s3)",
        }}
      >
        <strong>What the KICD design asks for: </strong>
        {fragment.kicd}
      </p>

      {open ? (
        <>
          <Textarea
            rows={20}
            value={text}
            spellCheck={false}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)}
            style={{ fontFamily: "var(--mono, monospace)", fontSize: "var(--text-sm)" }}
          />
          <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)" }}>
            <Button
              size="sm"
              disabled={!changed || save.isPending}
              onClick={() => save.mutate({ name: fragment.name, body: text })}
            >
              {save.isPending ? "Saving…" : "Save to Langfuse"}
            </Button>
            <Button size="sm" variant="ghost" disabled={!changed} onClick={() => setText(fragment.body)}>
              Back to the built-in
            </Button>
          </Stack>
          <p style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            Saved under <code>{fragment.langfuse_name}</code>, versioned like every
            other prompt. The built-in text stays in the code as the default, so a
            fresh deployment works with no prompt store at all.
          </p>
          {save.error && <ErrorNotice error={save.error} />}
        </>
      ) : (
        <pre
          style={{
            margin: 0,
            maxHeight: 220,
            overflow: "auto",
            fontSize: "var(--text-sm)",
            background: "var(--surface-2)",
            padding: "var(--s3)",
            borderRadius: "var(--radius-sm)",
            whiteSpace: "pre-wrap",
          }}
        >
          {fragment.body}
        </pre>
      )}
    </Card>
  );
}

/**
 * Every prompt as a project: download the folder, edit it anywhere, upload it.
 *
 * One textarea at a time is the wrong shape for the work that matters. Making
 * the chemistry fragment agree with the notation block, or every authoring
 * prompt use the same register language, is work across the whole set at once —
 * and a console that only ever shows one is a console in which that work does
 * not get done. So: thirty files, your own editor, one upload back.
 *
 * The upload is two steps, like every other path here that cannot be undone.
 * Prompts are the behaviour of every generator in the system, and an upload
 * that turns out to have been the wrong folder is not something to find out
 * from the output a week later.
 */
function ACTION_TONE(action: PromptChange["action"], promotable: boolean) {
  if (action === "changed") return promotable ? "ok" : "danger";
  if (action === "new") return "accent";
  if (action === "unknown" || action === "empty") return "warn";
  return "neutral";
}

function PlanRow({ change }: { change: PromptChange }) {
  const tone = ACTION_TONE(change.action, change.promotable);
  const delta = change.now - change.was;
  return (
    <div
      style={{
        borderTop: "1px solid var(--line)",
        padding: "var(--s2) 0",
        fontSize: "var(--text-sm)",
      }}
    >
      <Stack direction="row" gap="var(--s2)" align="center" wrap>
        <Badge tone={tone as any}>
          {change.action === "changed" && !change.promotable ? "staging only" : change.action}
        </Badge>
        <span className="mono">{change.name}</span>
        {change.action === "changed" && (
          <span style={{ color: "var(--ink-3)" }}>
            {delta >= 0 ? `+${delta}` : delta} characters
          </span>
        )}
        {change.aliases.length > 0 && (
          <span style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
            also written to {change.aliases.join(", ")}
          </span>
        )}
      </Stack>
      {change.errors.map((e, i) => (
        <div key={i} style={{ color: "var(--danger)", marginTop: 2 }}>{e}</div>
      ))}
      {change.warnings.map((w, i) => (
        <div key={i} style={{ color: "var(--warn)", marginTop: 2 }}>{w}</div>
      ))}
      {change.note && (
        <div style={{ color: "var(--ink-3)", marginTop: 2 }}>{change.note}</div>
      )}
    </div>
  );
}

export function PromptBundle() {
  const download = useExportPrompts();
  const upload = useImportPrompts();
  const [file, setFile] = React.useState<File | null>(null);
  const [allowNew, setAllowNew] = React.useState(false);
  const [plan, setPlan] = React.useState<PromptImportPlan | null>(null);
  const input = React.useRef<HTMLInputElement>(null);

  // A plan describes one file. Choosing a different one must throw it away, or
  // the confirm button applies a bundle nobody read the plan for.
  function choose(next: File | null) {
    setFile(next);
    setPlan(null);
  }

  const interesting = (plan?.changes || []).filter((c) => c.action !== "unchanged");

  return (
    <Card
      title="Edit them all at once"
      description="Download every prompt as a folder of Markdown files, edit them wherever you actually write, and bring the folder back as one upload."
    >
      <Stack gap="var(--s3)">
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          <Button
            onClick={() => download.mutateAsync()}
            loading={download.isPending}
            disabled={download.isPending}
          >
            {download.isPending ? "Preparing…" : "Download all prompts"}
          </Button>
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            The text currently serving, not the built-in defaults — so uploading
            it back changes nothing.
          </span>
        </Stack>

        <div style={{ borderTop: "1px solid var(--line)", paddingTop: "var(--s3)" }}>
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <input
              ref={input}
              type="file"
              accept=".zip,application/zip"
              aria-label="Edited prompt bundle"
              onChange={(e) => choose(e.target.files?.[0] || null)}
              style={{ fontSize: "var(--text-sm)" }}
            />
            <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              <input
                type="checkbox"
                checked={allowNew}
                onChange={(e) => setAllowNew(e.target.checked)}
              />{" "}
              Accept names I have not used before
            </label>
          </Stack>
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginTop: 4 }}>
            Unticked, a file whose name matches no known prompt is reported and
            skipped — that is nearly always a typo in a folder name, and
            accepting it makes an orphan while the real prompt keeps serving its
            old text.
          </div>

          <Stack direction="row" gap="var(--s2)" align="center" style={{ marginTop: "var(--s2)" }}>
            <Button
              variant="secondary"
              disabled={!file || upload.isPending}
              loading={upload.isPending && !plan}
              onClick={async () =>
                file && setPlan(await upload.mutateAsync({ file, allowNew }))
              }
            >
              See what would change
            </Button>
            {plan && !plan.applied && interesting.length > 0 && (
              <Button
                variant="primary"
                disabled={upload.isPending}
                loading={upload.isPending}
                onClick={async () =>
                  file &&
                  setPlan(
                    await upload.mutateAsync({
                      file, allowNew, confirm: plan.confirm_with,
                    })
                  )
                }
              >
                Write {plan.summary.changed + plan.summary.new} prompt(s)
              </Button>
            )}
          </Stack>
        </div>

        {upload.error && <ErrorNotice error={upload.error} />}

        {plan && (
          <div>
            {plan.applied ? (
              <Badge tone={plan.failed?.length ? "danger" : "ok"}>
                {plan.message}
              </Badge>
            ) : interesting.length === 0 ? (
              <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: 0 }}>
                Nothing in that bundle differs from what is already serving.
              </p>
            ) : (
              <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: 0 }}>
                <strong>Nothing has been written yet.</strong>{" "}
                {plan.summary.changed} changed, {plan.summary.unchanged} unchanged
                {plan.summary.blocked > 0 && (
                  <>
                    , <strong>{plan.summary.blocked}</strong> that would break
                    production and will be left in staging
                  </>
                )}
                .
              </p>
            )}

            {interesting.map((c) => (
              <PlanRow key={c.name} change={c} />
            ))}

            {plan.absent_note && (
              <div
                style={{
                  marginTop: "var(--s2)",
                  fontSize: "var(--text-sm)",
                  color: "var(--ink-3)",
                }}
              >
                {plan.absent_note}
              </div>
            )}
          </div>
        )}
      </Stack>
    </Card>
  );
}

export function PromptFragments({
  subject = "",
  grade = "",
  station = "",
  compact = false,
}: {
  subject?: string;
  grade?: string;
  station?: string;
  /** On the board, only what applies here. On its own screen, all of them. */
  compact?: boolean;
}) {
  const [filter, setFilter] = React.useState(subject);
  const { list } = usePromptFragments(compact ? subject : filter, grade, station);

  if (list.isLoading) return <LoadingBlock rows={4} label="Loading the domain prompts" />;
  if (list.isError) return <ErrorNotice error={list.error} />;

  const all = list.data?.fragments || [];
  const shown = compact ? all.filter((f) => f.applies_here) : all;

  if (compact && !shown.length) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        No domain prompt applies to {subject || "this subject"} at this stage —
        which is usually right. A lesson plan about God needs no paragraph on
        mortise and tenon joints.
      </p>
    );
  }

  return (
    <Stack gap="var(--s3)" style={{ marginTop: compact ? "var(--s3)" : 0 }}>
      {!compact && <PromptBundle />}
      {!compact && (
        <Field label="Show what applies to" hint="Leave empty to see all of them">
          {(a11y) => (
            <Input
              {...a11y}
              value={filter}
              placeholder="Geography, Chemistry, Music…"
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFilter(e.target.value)}
            />
          )}
        </Field>
      )}
      {shown.map((f) => (
        <Fragment key={f.name} fragment={f} />
      ))}
    </Stack>
  );
}
