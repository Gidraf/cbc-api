import React from "react";
import { useNavigate } from "react-router-dom";

import { Badge, Button, Input, Select, Spinner, Stack } from "./components";
import { useSetStageBinding, useStageAction, useStageBindings } from "../lib/queries";

/**
 * What to do about it, next to the thing that went wrong.
 *
 * An error here usually has exactly one sensible next move, and the operator
 * had to know what it was. "No approved lesson plan" meant: go to the board,
 * find the grade, find the learning area, find the lesson plan stage, run it,
 * wait, review it, approve it, come back — six navigations to act on one
 * sentence, in a console with fifteen grades and nine stages, every one of them
 * a chance to act on the wrong row.
 *
 * Three shapes, because there are three kinds of next move:
 *
 *   run   queue the work that is missing, here. Several stages run ONE AT A
 *         TIME and in order — each is built from the one before it, so firing
 *         them together fails all but the first, which is exactly the failure
 *         the remedy exists to prevent.
 *   set   a value is wrong and can be typed. A model id the provider does not
 *         have is not a workflow problem; it is a text field, so it is a text
 *         field here.
 *   open  the fix needs judgement, so it goes to where the judgement is made.
 *         Approval is the case: a person signs, and no error offers to sign
 *         for them.
 */

export type RemedyStep = { stage: string; label: string };

export type Remedy = {
  kind: "run" | "set" | "open";
  label: string;
  why?: string;
  stage?: string;
  grade?: string;
  subject?: string;
  steps?: RemedyStep[];
  sequential?: boolean;
  field_name?: string;
  current?: string;
  options?: string[];
  href?: string;
};

/** Pull remedies off whatever the API threw. */
export function remediesOf(error: unknown): Remedy[] {
  const body = (error as any)?.data;
  const first = body?.errors?.[0];
  const found = first?.remedy || body?.remedy;
  return Array.isArray(found) ? (found as Remedy[]) : [];
}

/** Run the missing stages, in order, saying which one it is on. */
function RunRemedy({ remedy, onDone }: { remedy: Remedy; onDone?: () => void }) {
  const { act } = useStageAction();
  const steps = remedy.steps?.length
    ? remedy.steps
    : [{ stage: remedy.stage || "", label: remedy.label }];
  const [at, setAt] = React.useState(-1);
  const [done, setDone] = React.useState<string[]>([]);
  const [failed, setFailed] = React.useState("");

  async function go() {
    setFailed("");
    for (let i = 0; i < steps.length; i++) {
      setAt(i);
      try {
        await act.mutateAsync({
          grade: remedy.grade || "",
          subject: remedy.subject || "",
          stage: steps[i].stage,
          action: "run",
        });
        setDone((d) => [...d, steps[i].stage]);
      } catch (e: any) {
        // Stop at the first failure rather than queueing the rest. The steps
        // after it depend on this one, so carrying on only buries the reason.
        setFailed(`${steps[i].label}: ${e?.message || "could not be queued"}`);
        setAt(-1);
        return;
      }
    }
    setAt(-1);
    onDone?.();
  }

  const running = at >= 0;
  return (
    <Stack gap="var(--s2)">
      <Stack direction="row" gap="var(--s2)" align="center" wrap>
        <Button size="sm" onClick={go} disabled={running} loading={running}>
          {running ? `Queueing ${steps[at]?.label}…` : remedy.label}
        </Button>
        {steps.length > 1 && (
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            {steps.map((s, i) => (
              <span key={s.stage}>
                {i > 0 && " → "}
                <span
                  style={{
                    color: done.includes(s.stage)
                      ? "var(--ok)"
                      : at === i
                        ? "var(--accent)"
                        : "var(--ink-3)",
                  }}
                >
                  {done.includes(s.stage) ? "✓ " : ""}
                  {s.label}
                </span>
              </span>
            ))}
          </span>
        )}
        {running && <Spinner />}
      </Stack>
      {failed && (
        <div style={{ fontSize: "var(--text-sm)", color: "var(--danger)" }}>
          Stopped at {failed}
        </div>
      )}
      {done.length > 0 && at < 0 && !failed && (
        <Badge tone="ok">
          {done.length === 1
            ? "Queued. It will appear on the board as it runs."
            : `All ${done.length} queued, in order.`}
        </Badge>
      )}
    </Stack>
  );
}

/** Fix the field that is wrong, without going to find it. */
function SetRemedy({ remedy }: { remedy: Remedy }) {
  const bindings = useStageBindings();
  const save = useSetStageBinding();
  const [value, setValue] = React.useState(remedy.current || "");
  const [saved, setSaved] = React.useState(false);

  const row = (bindings.data?.stages || []).find((b) => b.name === remedy.stage);
  const options = remedy.options || [];

  if (saved) {
    return (
      <Badge tone="ok">
        {remedy.stage} now uses {value}. Run it again.
      </Badge>
    );
  }

  return (
    <Stack direction="row" gap="var(--s2)" align="center" wrap>
      {options.length > 0 ? (
        <Select
          aria-label="Model"
          value={value}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setValue(e.target.value)}
          style={{ minWidth: "13rem" }}
        >
          {/* The current value stays selectable even though it failed: a
              provider can add a model this list has never heard of, and a
              picker that silently drops what is bound hides what is bound. */}
          {!options.includes(value) && value && <option value={value}>{value} (current)</option>}
          {options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </Select>
      ) : (
        <Input
          aria-label="Model"
          className="mono"
          value={value}
          placeholder="model id"
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setValue(e.target.value)}
          style={{ minWidth: "13rem" }}
        />
      )}
      <Button
        size="sm"
        disabled={!value || value === remedy.current || save.isPending}
        loading={save.isPending}
        onClick={async () => {
          await save.mutateAsync({
            stage: remedy.stage || "",
            provider: row?.provider || "",
            model: value,
          });
          setSaved(true);
        }}
      >
        {remedy.label}
      </Button>
    </Stack>
  );
}

export function RemedyActions({
  remedies,
  onDone,
}: {
  remedies: Remedy[];
  onDone?: () => void;
}) {
  const navigate = useNavigate();
  if (!remedies.length) return null;

  return (
    <Stack gap="var(--s3)" style={{ width: "100%" }}>
      {remedies.map((remedy, i) => (
        <Stack key={i} gap="4px">
          {remedy.kind === "run" && <RunRemedy remedy={remedy} onDone={onDone} />}
          {remedy.kind === "set" && <SetRemedy remedy={remedy} />}
          {remedy.kind === "open" && (
            <Button size="sm" variant="secondary" onClick={() => navigate(remedy.href || "/")}>
              {remedy.label}
            </Button>
          )}
          {remedy.why && (
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {remedy.why}
            </span>
          )}
        </Stack>
      ))}
    </Stack>
  );
}
