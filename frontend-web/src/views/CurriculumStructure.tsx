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
  Textarea,
  Th,
} from "../ui/components";
import { allStrandsToText, strandToText } from "../lib/serialize";
import {
  useStructureActions,
  type GeneratedStrand,
  type GeneratedSubstrand,
} from "../lib/queries";

/**
 * Build a subject's strands and sub-strands with the curriculum agent.
 *
 * A design whose layout the text parser cannot read — Pre-Primary is organised
 * by activity areas rather than "STRAND 1.0" headings — ingests successfully
 * and yields no sub-strands. Everything downstream is keyed on sub-strands, so
 * the grade looks empty. This is the path back: generate the structure, review
 * it, then save it.
 *
 * Nothing is written until Save. Generation is a draft you can discard.
 */

const strandName = (s: GeneratedStrand) => s.strand_name || s.name || "";
const strandId = (s: GeneratedStrand) => s.strand_id || "1.0";

const subName = (s: GeneratedSubstrand) =>
  s.sub_strand_name || s.name || s.sub_strand || "Untitled sub-strand";
const subHours = (s: GeneratedSubstrand) => s.allocated_hours || s.hours || "—";
const subCount = (s: GeneratedSubstrand, key: string) => {
  const v = s[key];
  return Array.isArray(v) ? v.length : 0;
};

export function CurriculumStructure({
  grade,
  subject,
  onSaved,
}: {
  grade: string;
  subject: string;
  onSaved?: () => void;
}) {
  const actions = useStructureActions(grade, subject);
  const [strands, setStrands] = React.useState<GeneratedStrand[]>([]);
  const [openStrand, setOpenStrand] = React.useState<string | null>(null);
  const [drafts, setDrafts] = React.useState<Record<string, GeneratedSubstrand[]>>({});
  const [saved, setSaved] = React.useState<Record<string, number>>({});
  const [instructions, setInstructions] = React.useState("");
  // Whether the last generation actually read the KICD design, or produced a
  // plausible curriculum from the model's own knowledge.
  const [grounded, setGrounded] = React.useState<{ ok: boolean; chars: number } | null>(null);

  const busy =
    actions.generateStrands.isPending ||
    actions.generateSubstrands.isPending ||
    actions.saveSubstrands.isPending;

  async function makeStrands() {
    const res = await actions.generateStrands.mutateAsync({ custom_instructions: instructions });
    setStrands(res.strands || []);
    setGrounded({ ok: Boolean(res.grounded), chars: res.source_chars ?? 0 });
  }

  async function makeSubstrands(strand: GeneratedStrand) {
    const name = strandName(strand);
    setOpenStrand(name);
    const res = await actions.generateSubstrands.mutateAsync({
      strand_name: name,
      strand_id: strandId(strand),
      custom_instructions: instructions,
    });
    setDrafts((d) => ({ ...d, [name]: res.sub_strands || [] }));
  }

  async function save(strand: GeneratedStrand) {
    const name = strandName(strand);
    const substrands = drafts[name] || [];
    if (!substrands.length) return;
    await actions.saveSubstrands.mutateAsync({
      strand_name: name,
      strand_id: strandId(strand),
      substrands,
    });
    setSaved((s) => ({ ...s, [name]: substrands.length }));
    setDrafts((d) => {
      const next = { ...d };
      delete next[name];
      return next;
    });
    onSaved?.();
  }

  function discard(name: string) {
    setDrafts((d) => {
      const next = { ...d };
      delete next[name];
      return next;
    });
  }

  return (
    <Card
      title="Build the curriculum structure"
      description={`Generate strands and sub-strands for ${subject || "this subject"} with the curriculum agent. Nothing is written until you save.`}
      actions={
        <Stack direction="row" gap="var(--s2)">
        {strands.length > 0 && (
          <CopyButton
            label="Copy all"
            title="Copy every strand and its drafted sub-strands, to check in another model"
            getText={() =>
              allStrandsToText(strands, drafts, { grade, subject })
            }
          />
        )}
        <Button size="sm" disabled={busy || !subject} onClick={makeStrands}>
          {actions.generateStrands.isPending
            ? "Generating…"
            : strands.length
            ? "Regenerate strands"
            : "Generate strands"}
        </Button>
        </Stack>
      }
    >
      {actions.generateStrands.error && <ErrorNotice error={actions.generateStrands.error} />}

      {grounded && !grounded.ok && (
        <EmptyState
          title="Generated without the curriculum design"
          description="No source document was found for this subject, so these strands come from the model's own knowledge rather than the KICD design. They will read plausibly and may match nothing KICD published. Ingest the design for this subject first."
          tone="warn"
        />
      )}
      {grounded && grounded.ok && (
        <div style={{ marginBottom: "var(--s3)" }}>
          <Badge tone="ok">
            Read from the KICD design ({(grounded.chars / 1000).toFixed(0)}k characters)
          </Badge>
        </div>
      )}
      {actions.generateSubstrands.error && <ErrorNotice error={actions.generateSubstrands.error} />}
      {actions.saveSubstrands.error && <ErrorNotice error={actions.saveSubstrands.error} />}

      <div style={{ marginBottom: "var(--s4)" }}>
        <Textarea
          aria-label="Extra instructions for the curriculum agent"
          placeholder="Optional: anything the agent should know — a KICD revision year, a pathway, terminology to follow."
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={2}
        />
      </div>

      {strands.length === 0 ? (
        <EmptyState
          title="No strands yet"
          description={
            subject
              ? "Generate strands to start. You can edit or regenerate before anything is saved."
              : "Choose a subject first."
          }
        />
      ) : (
        <Stack gap="var(--s3)">
          {strands.map((strand) => {
            const name = strandName(strand);
            const draft = drafts[name];
            const savedCount = saved[name];
            const isOpen = openStrand === name;

            return (
              <div
                key={name || strandId(strand)}
                style={{
                  border: "1px solid var(--line-2)",
                  borderRadius: "var(--radius-sm)",
                  padding: "var(--s3)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)" }}>
                  <strong style={{ flex: 1 }}>{name}</strong>
                  {savedCount !== undefined && <Badge tone="ok">{savedCount} saved</Badge>}
                  {draft && <Badge tone="warn">{draft.length} draft</Badge>}
                  <CopyButton
                    label="Copy"
                    title="Copy this strand and its sub-strands"
                    getText={() => strandToText(strand, drafts[name], { grade, subject })}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => makeSubstrands(strand)}
                  >
                    {actions.generateSubstrands.isPending && isOpen
                      ? "Generating…"
                      : draft
                      ? "Regenerate sub-strands"
                      : "Generate sub-strands"}
                  </Button>
                </div>

                {strand.description && (
                  <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: 4 }}>
                    {strand.description}
                  </div>
                )}

                {draft && draft.length > 0 && (
                  <div style={{ marginTop: "var(--s3)" }}>
                    <Table caption={`Sub-strands drafted for ${name}`}>
                      <thead>
                        <tr>
                          <Th>Sub-strand</Th>
                          <Th numeric>Hours</Th>
                          <Th numeric>Outcomes</Th>
                          <Th numeric>Diagrams</Th>
                          <Th numeric>Experiments</Th>
                          <Th />
                        </tr>
                      </thead>
                      <tbody>
                        {draft.map((sub, i) => (
                          <tr key={i}>
                            <Td>{subName(sub)}</Td>
                            <Td numeric>{subHours(sub)}</Td>
                            <Td numeric>{subCount(sub, "slos")}</Td>
                            <Td numeric>{subCount(sub, "required_diagrams")}</Td>
                            <Td numeric>{subCount(sub, "experiments")}</Td>
                            <Td>
                              <CopyButton
                                label="Copy"
                                title="Copy just this sub-strand"
                                getText={() =>
                                  strandToText(strand, [sub], { grade, subject })
                                }
                              />
                            </Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                    <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s3)" }}>
                      <Button size="sm" disabled={busy} onClick={() => save(strand)}>
                        {actions.saveSubstrands.isPending ? "Saving…" : `Save ${draft.length} sub-strands`}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => discard(name)}>
                        Discard
                      </Button>
                    </Stack>
                  </div>
                )}
              </div>
            );
          })}
        </Stack>
      )}
    </Card>
  );
}
