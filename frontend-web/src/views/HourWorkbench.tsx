import React from "react";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorNotice,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { allHoursToText, hourToText, toReadable } from "../lib/serialize";
import {
  VISUAL_MODES,
  forHour,
  hourModulesOf,
  useHourActions,
  type HourModule,
  type VisualMode,
} from "../lib/queries";

/**
 * Produce a sub-strand's assets hour by hour.
 *
 * KICD allocates hours to a sub-strand, the notes generator returns one module
 * per hour, and every diagram, photo prompt, video prompt, experiment and
 * activity belongs to a specific hour — not to the sub-strand as a whole. The
 * backend has always modelled this (hour_index on planned visuals, target_hour
 * on rendered ones); this screen stops flattening it.
 */

const titleOf = (item: any, fallback: string) =>
  item?.title || item?.activity_name || item?.experiment_title || item?.name || fallback;

export function HourWorkbench({
  grade,
  subject,
  strand,
  subStrand,
  notes,
  allocatedHours,
}: {
  grade: string;
  subject: string;
  strand: string;
  subStrand: string;
  notes: any;
  allocatedHours?: string;
}) {
  const actions = useHourActions(grade, subject);
  const hours = hourModulesOf(notes);
  const [active, setActive] = React.useState(1);
  const [visuals, setVisuals] = React.useState<any[]>([]);
  const [activities, setActivities] = React.useState<any[]>([]);
  const [rendered, setRendered] = React.useState<Record<string, any>>({});
  const [working, setWorking] = React.useState<string | null>(null);

  const busy =
    actions.planVisuals.isPending ||
    actions.planActivities.isPending ||
    actions.renderVisual.isPending ||
    actions.buildActivity.isPending;

  if (!notes) {
    return (
      <EmptyState
        title="Generate the lesson notes first"
        description="Hours come from the notes, and every diagram, photo, video and experiment hangs off an hour."
      />
    );
  }

  if (hours.length === 0) {
    return (
      <EmptyState
        title="These notes have no hour modules"
        description={
          "The notes generator returns one module per KICD-allocated hour. Regenerate the " +
          "notes for this sub-strand — without hours there is nothing to anchor assets to."
        }
        tone="warn"
      />
    );
  }

  const common = { strand, sub_strand: subStrand, notes_content: notes };

  async function plan() {
    const [v, a] = await Promise.all([
      actions.planVisuals.mutateAsync({ ...common }),
      actions.planActivities.mutateAsync({ ...common }),
    ]);
    setVisuals(v.visuals || []);
    setActivities(a.activities || []);
  }

  async function render(item: any, mode: VisualMode, hour: number) {
    const key = `${hour}:${titleOf(item, "visual")}:${mode}`;
    setWorking(key);
    try {
      const res = await actions.renderVisual.mutateAsync({
        ...common,
        visual_item: item,
        generation_mode: mode,
        target_hour: hour,
      });
      setRendered((r) => ({ ...r, [key]: res }));
    } finally {
      setWorking(null);
    }
  }

  async function build(item: any, hour: number) {
    const key = `${hour}:${titleOf(item, "activity")}:activity`;
    setWorking(key);
    try {
      const res = await actions.buildActivity.mutateAsync({
        ...common,
        activity_item: item,
        target_hour: hour,
      });
      setRendered((r) => ({ ...r, [key]: res }));
    } finally {
      setWorking(null);
    }
  }

  const hourVisuals = forHour(visuals, active);
  const hourActivities = forHour(activities, active);
  const planned = visuals.length > 0 || activities.length > 0;

  return (
    <Card
      title="Produce hour by hour"
      description={`${hours.length} hour module${hours.length === 1 ? "" : "s"}${
        allocatedHours ? ` · KICD allocates ${allocatedHours}` : ""
      }. Diagrams, photo and video prompts, experiments and activities all belong to a specific hour.`}
      actions={
        <Stack direction="row" gap="var(--s2)">
        <CopyButton
          label="Copy all hours"
          title="Copy every hour's notes and its planned assets, to check in another model"
          getText={() =>
            allHoursToText(
              hours,
              (h) => forHour(visuals, h),
              (h) => forHour(activities, h),
              { grade, subject, strand, "sub strand": subStrand }
            )
          }
        />
        <Button size="sm" disabled={busy} onClick={plan}>
          {actions.planVisuals.isPending || actions.planActivities.isPending
            ? "Planning…"
            : planned
            ? "Re-plan all hours"
            : "Plan assets for all hours"}
        </Button>
        </Stack>
      }
    >
      {actions.planVisuals.error && <ErrorNotice error={actions.planVisuals.error} />}
      {actions.planActivities.error && <ErrorNotice error={actions.planActivities.error} />}
      {actions.renderVisual.error && <ErrorNotice error={actions.renderVisual.error} />}
      {actions.buildActivity.error && <ErrorNotice error={actions.buildActivity.error} />}

      {/* Hour selector */}
      <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s4)" }}>
        {hours.map((h: HourModule) => {
          const n = h.hour_index as number;
          const count = forHour(visuals, n).length + forHour(activities, n).length;
          return (
            <Button
              key={n}
              size="sm"
              variant={n === active ? "primary" : "secondary"}
              onClick={() => setActive(n)}
            >
              Hour {n}
              {count > 0 ? ` · ${count}` : ""}
            </Button>
          );
        })}
      </Stack>

      {hours
        .filter((h) => h.hour_index === active)
        .map((h) => (
          <div key={h.hour_index} style={{ marginBottom: "var(--s4)" }}>
            <Stack direction="row" gap="var(--s3)" align="center" style={{ marginBottom: 4 }}>
              <strong style={{ flex: 1 }}>{h.hour_title}</strong>
              <CopyButton
                label="Copy this hour"
                getText={() =>
                  hourToText(h, forHour(visuals, active), forHour(activities, active), {
                    grade, subject, strand, "sub strand": subStrand,
                  })
                }
              />
            </Stack>
            <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", lineHeight: 1.6 }}>
              {String(h.full_lecture_notes || h.summary || "").slice(0, 420) || "No lecture text in this module."}
              {String(h.full_lecture_notes || "").length > 420 ? "…" : ""}
            </div>
          </div>
        ))}

      {!planned ? (
        <EmptyState
          title="Nothing planned yet"
          description="Plan the assets to see what each hour needs, then render each one as a diagram, photo prompt or video."
        />
      ) : (
        <Stack gap="var(--s5)">
          <div>
            <Th>Visuals for hour {active}</Th>
            {hourVisuals.length === 0 ? (
              <EmptyState title="No visuals planned for this hour" />
            ) : (
              <Table caption={`Visuals for hour ${active}`}>
                <thead>
                  <tr>
                    <Th>Visual</Th>
                    <Th>Micro-concept</Th>
                    <Th>Render as</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {hourVisuals.map((v, i) => (
                    <tr key={i}>
                      <Td>{titleOf(v, `Visual ${i + 1}`)}</Td>
                      <Td>{v.micro_concept || v.pedagogical_purpose || "—"}</Td>
                      <Td>
                        <Stack direction="row" gap="var(--s2)" wrap>
                          {VISUAL_MODES.map((m) => {
                            const key = `${active}:${titleOf(v, "visual")}:${m.id}`;
                            const done = rendered[key];
                            return (
                              <Button
                                key={m.id}
                                size="sm"
                                variant={done ? "primary" : "ghost"}
                                disabled={busy}
                                title={m.hint}
                                onClick={() => render(v, m.id, active)}
                              >
                                {working === key ? "…" : done ? `✓ ${m.label}` : m.label}
                              </Button>
                            );
                          })}
                        </Stack>
                      </Td>
                      <Td>
                        <CopyButton
                          label="Copy"
                          title="Copy this visual, including anything rendered from it"
                          getText={() => {
                            const made = VISUAL_MODES
                              .map((m) => rendered[`${active}:${titleOf(v, "visual")}:${m.id}`])
                              .filter(Boolean);
                            return toReadable({ visual: v, rendered: made });
                          }}
                        />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </div>

          <div>
            <Th>Experiments and activities for hour {active}</Th>
            {hourActivities.length === 0 ? (
              <EmptyState title="No activities planned for this hour" />
            ) : (
              <Table caption={`Activities for hour ${active}`}>
                <thead>
                  <tr>
                    <Th>Activity</Th>
                    <Th>Type</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {hourActivities.map((a, i) => {
                    const key = `${active}:${titleOf(a, "activity")}:activity`;
                    const done = rendered[key];
                    return (
                      <tr key={i}>
                        <Td>{titleOf(a, `Activity ${i + 1}`)}</Td>
                        <Td>
                          <Badge tone={a.experiment_title ? "warn" : "info"}>
                            {a.experiment_title ? "Experiment" : a.activity_type || "Activity"}
                          </Badge>
                        </Td>
                        <Td>
                          <Button
                            size="sm"
                            variant={done ? "primary" : "ghost"}
                            disabled={busy}
                            onClick={() => build(a, active)}
                          >
                            {working === key ? "Building…" : done ? "✓ Built" : "Build in full"}
                          </Button>
                          <CopyButton
                            label="Copy"
                            title="Copy this activity, including the built detail"
                            getText={() => toReadable({ activity: a, built: done })}
                          />
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </div>
        </Stack>
      )}
    </Card>
  );
}
