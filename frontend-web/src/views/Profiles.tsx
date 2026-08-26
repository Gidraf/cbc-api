import React from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Field,
  Grid,
  Input,
  Modal,
  PageHeader,
  QueryState,
  Select,
  Stack,
  Stat,
  Table,
  Td,
  Textarea,
  Th,
  useToast,
} from "../ui/components";
import {
  gradeOptionLabel,
  useDesigns,
  useGrades,
  useProfileActions,
  useProfiles,
  type Profile,
} from "../lib/queries";

/**
 * Teaching skills, one per subject and grade.
 *
 * A profile is the professor's know-how for a subject: the persona to write as,
 * how notes should read, what kind of diagram and activity suit it, how it
 * should be assessed, and what safety demands it carries. The classifier looks
 * one up by (subject, grade) and injects it into the notes, diagram, activity
 * and question prompts — so a subject without one is generated unskilled, which
 * is invisible in the output until a teacher tells you it reads wrong.
 */

const FIELDS: { key: keyof Profile; label: string; hint: string; rows?: number }[] = [
  { key: "persona", label: "Persona", hint: "Who is writing — the specialist voice to adopt", rows: 2 },
  { key: "note_style", label: "Note style", hint: "How lesson notes should read for this subject", rows: 2 },
  { key: "diagram_type", label: "Diagram type", hint: "The visuals this subject actually needs", rows: 2 },
  { key: "activity_type", label: "Activity type", hint: "Practical work appropriate to it", rows: 2 },
  { key: "question_type", label: "Question type", hint: "How this subject is properly assessed", rows: 2 },
  { key: "safety_focus", label: "Safety focus", hint: "Hazards that must be addressed", rows: 2 },
];

const empty = (): Profile => ({
  subject: "",
  grade: "all",
  persona: "",
  note_style: "",
  diagram_type: "",
  activity_type: "",
  question_type: "",
  safety_focus: "",
  grade_appropriate_tone: "formal academic and constructivist",
  special_directives: [],
});

export function Profiles() {
  const toast = useToast();
  const grades = useGrades();
  const [gradeFilter, setGradeFilter] = React.useState("");
  const [search, setSearch] = React.useState("");
  const profiles = useProfiles(search, gradeFilter);
  const designs = useDesigns();
  const actions = useProfileActions();

  const [editing, setEditing] = React.useState<Profile | null>(null);
  const [improveWith, setImproveWith] = React.useState("");
  const [designPicker, setDesignPicker] = React.useState(false);

  const busy =
    actions.save.isPending ||
    actions.aiGenerate.isPending ||
    actions.fromDesign.isPending ||
    actions.improve.isPending;

  const covered = new Set((profiles.data || []).map((p) => `${p.subject}|${p.grade}`.toLowerCase()));
  const designsWithoutSkill = (designs.data || []).filter(
    (d) =>
      !covered.has(`${d.subject}|${d.grade}`.toLowerCase()) &&
      !covered.has(`${d.subject}|all`.toLowerCase())
  );

  async function fromDesign(designId: string) {
    const res = await actions.fromDesign.mutateAsync(designId);
    setDesignPicker(false);
    setEditing(res.profile);
    toast("Skill drafted from the design — review it before it steers generation.", "ok");
  }

  async function improve() {
    if (!editing || !improveWith.trim()) return;
    const res = await actions.improve.mutateAsync({ profile: editing, instructions: improveWith });
    setEditing(res.profile);
    setImproveWith("");
  }

  async function save() {
    if (!editing) return;
    await actions.save.mutateAsync(editing);
    setEditing(null);
  }

  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Teaching skills"
        description="One profile per subject and grade, derived from its KICD design. It sets the persona, note style, diagram and activity types, assessment approach and safety focus — and is injected into every generation prompt for that subject."
        actions={
          <Stack direction="row" gap="var(--s2)">
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => setDesignPicker(true)}>
              Draft from a design
            </Button>
            <Button size="sm" disabled={busy} onClick={() => setEditing(empty())}>
              New skill
            </Button>
          </Stack>
        }
      />

      <Grid min="200px">
        <Stat label="Skills defined" value={`${profiles.data?.length ?? 0}`} sub="Subjects that generate with expertise" />
        <Stat
          label="Designs without a skill"
          value={`${designsWithoutSkill.length}`}
          sub="These generate unskilled until covered"
        />
        <Stat label="Curriculum designs" value={`${designs.data?.length ?? 0}`} sub="Ingested and available" />
      </Grid>

      {actions.save.error && <ErrorNotice error={actions.save.error} />}
      {actions.fromDesign.error && <ErrorNotice error={actions.fromDesign.error} />}
      {actions.aiGenerate.error && <ErrorNotice error={actions.aiGenerate.error} />}

      <Card
        title="Skills"
        description="Each is looked up by subject and grade when content is generated."
        actions={
          <Stack direction="row" gap="var(--s2)">
            <Input
              aria-label="Search skills"
              placeholder="Search subject…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 180 }}
            />
            <Select
              aria-label="Grade"
              value={gradeFilter}
              onChange={(e) => setGradeFilter(e.target.value)}
              style={{ width: "auto" }}
            >
              <option value="">All grades</option>
              {(grades.data || []).map((g) => (
                <option key={g.slug || g.name} value={g.slug || g.name}>
                  {gradeOptionLabel(g)}
                </option>
              ))}
            </Select>
          </Stack>
        }
      >
        <QueryState query={profiles} label="Loading skills" rows={3} />
        {profiles.data && profiles.data.length === 0 ? (
          <EmptyState
            title="No skills defined"
            description="Every subject currently generates with a generic profile. Draft one from an ingested design to give it real expertise."
            tone="warn"
          />
        ) : (
          <Table caption="Teaching skills">
            <thead>
              <tr>
                <Th>Subject</Th>
                <Th>Grade</Th>
                <Th>Persona</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(profiles.data || []).map((p) => (
                <tr key={p.id ?? `${p.subject}-${p.grade}`}>
                  <Td>{p.subject}</Td>
                  <Td>
                    <Badge tone={p.grade === "all" ? "info" : "neutral"}>{p.grade || "all"}</Badge>
                  </Td>
                  <Td>
                    <span style={{ color: "var(--ink-2)" }}>
                      {(p.persona || "").slice(0, 90)}
                      {(p.persona || "").length > 90 ? "…" : ""}
                    </span>
                  </Td>
                  <Td>
                    <Stack direction="row" gap="var(--s2)">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                        Edit
                      </Button>
                      {p.id !== undefined && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(`Delete the ${p.subject} skill? That subject will generate unskilled.`)) {
                              actions.remove.mutate(p.id!);
                            }
                          }}
                        >
                          Delete
                        </Button>
                      )}
                    </Stack>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {designsWithoutSkill.length > 0 && (
        <Card
          title={`${designsWithoutSkill.length} design${designsWithoutSkill.length === 1 ? "" : "s"} generating unskilled`}
          description="These have been ingested but no skill covers them, so their notes, diagrams and questions are produced with a generic profile."
        >
          <Table caption="Designs without a skill">
            <thead>
              <tr>
                <Th>Subject</Th>
                <Th>Grade</Th>
                <Th numeric>Sub-strands</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {designsWithoutSkill.slice(0, 12).map((d) => (
                <tr key={d.design_id}>
                  <Td>{d.subject}</Td>
                  <Td>{d.grade}</Td>
                  <Td numeric>{d.substrand_count ?? 0}</Td>
                  <Td>
                    <Button size="sm" disabled={busy} onClick={() => fromDesign(d.design_id)}>
                      {actions.fromDesign.isPending ? "Drafting…" : "Draft skill"}
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {designPicker && (
        <Modal open title="Draft a skill from a curriculum design" onClose={() => setDesignPicker(false)}>
          <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
            The design's essence statement, learning outcomes, sub-strands, inquiry questions,
            competencies and values are read to synthesise the skill. You review it before saving.
          </p>
          <QueryState query={designs} label="Loading designs" rows={3} />
          <Stack gap="var(--s2)" style={{ maxHeight: "50vh", overflowY: "auto" }}>
            {(designs.data || []).map((d) => (
              <Button
                key={d.design_id}
                variant="secondary"
                disabled={busy}
                onClick={() => fromDesign(d.design_id)}
                style={{ justifyContent: "flex-start" }}
              >
                {d.subject} · {d.grade} · {d.substrand_count ?? 0} sub-strands
              </Button>
            ))}
          </Stack>
        </Modal>
      )}

      {editing && (
        <Modal
          open
          title={editing.id ? `Edit skill — ${editing.subject}` : "New teaching skill"}
          onClose={() => setEditing(null)}
        >
          <Stack gap="var(--s3)">
            <Grid min="200px">
              <Field label="Subject">
                {(p) => (
                  <Input
                    {...p}
                    value={editing.subject}
                    onChange={(e) => setEditing({ ...editing, subject: e.target.value })}
                  />
                )}
              </Field>
              <Field label="Grade" hint="Use 'all' to cover every grade for this subject">
                {(p) => (
                  <Input
                    {...p}
                    value={editing.grade}
                    onChange={(e) => setEditing({ ...editing, grade: e.target.value })}
                  />
                )}
              </Field>
            </Grid>

            {FIELDS.map((f) => (
              <Field key={String(f.key)} label={f.label} hint={f.hint}>
                {(p) => (
                  <Textarea
                    {...p}
                    rows={f.rows ?? 2}
                    value={String(editing[f.key] ?? "")}
                    onChange={(e) => setEditing({ ...editing, [f.key]: e.target.value })}
                  />
                )}
              </Field>
            ))}

            <Field
              label="Refine with the AI"
              hint="Describe what to change and the skill is rewritten — you still review before saving."
            >
              {(p) => (
              <Stack direction="row" gap="var(--s2)">
                <Input
                  {...p}
                  placeholder="e.g. make the safety focus stricter for practical chemistry"
                  value={improveWith}
                  onChange={(e) => setImproveWith(e.target.value)}
                />
                <Button size="sm" variant="secondary" disabled={busy || !improveWith.trim()} onClick={improve}>
                  {actions.improve.isPending ? "Refining…" : "Refine"}
                </Button>
              </Stack>
              )}
            </Field>

            <Stack direction="row" gap="var(--s2)" justify="flex-end">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button
                disabled={busy || !editing.subject.trim() || !editing.persona.trim()}
                onClick={save}
              >
                {actions.save.isPending ? "Saving…" : "Save skill"}
              </Button>
            </Stack>
          </Stack>
        </Modal>
      )}
    </>
  );
}
