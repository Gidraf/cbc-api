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
import { DesignReader } from "./DesignReader";
import { VersionReview } from "./VersionReview";
import { PromptInspector, type Inspection } from "./PromptInspector";
import {
  useArtifacts,
  useDesigns,
  useInspect,
  useStoredStructure,
  useStructureActions,
  type GeneratedStrand,
  type GeneratedSubstrand,
  type Refusal,
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
 * Nothing is written until Save. Generation is a draft you can discard —
 * but what HAS been saved is read back on mount, so a reload shows the stored
 * structure rather than an empty page. Previously this view rendered only what
 * the current session had generated: saved sub-strands were in the database
 * the whole time and simply had no way of being found again.
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

/**
 * The saved sub-strands of one strand, each with its versions and review.
 *
 * Saving files a version per sub-strand; without a way through to it here, the
 * review layers exist and nobody arrives at them.
 */
function SubStrandVersions({
  grade,
  subject,
  names,
}: {
  grade: string;
  subject: string;
  names: string[];
}) {
  const [open, setOpen] = React.useState("");
  const artifacts = useArtifacts({ grade, subject, kind: "sub_strand", sub_strand: open });
  const found = artifacts.data?.artifacts?.[0];

  return (
    <div style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
        {names.map((name) => (
          <Button
            key={name}
            size="sm"
            variant={open === name ? "primary" : "ghost"}
            onClick={() => setOpen(open === name ? "" : name)}
            title={`Versions, review and approval for "${name}"`}
          >
            {open === name ? `▾ ${name}` : `▸ ${name}`}
          </Button>
        ))}
      </Stack>
      {open && (
        <div
          style={{
            marginTop: "var(--s3)",
            padding: "var(--s3)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius)",
          }}
        >
          {found ? (
            <VersionReview artifactId={found.artifact_id} />
          ) : (
            <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: 0 }}>
              {artifacts.isLoading
                ? "Loading versions…"
                : `No version filed for "${open}" yet. Sub-strands saved before versioning was added are in the database but were never filed as versions — regenerate and save to file one.`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

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
  const inspect = useInspect(grade, subject);
  const [inspection, setInspection] = React.useState<Inspection | null>(null);
  const [reading, setReading] = React.useState(false);

  // The design this subject and grade was ingested from, so it can be read
  // alongside what is being generated out of it.
  const designs = useDesigns();
  const design = (designs.data || []).find(
    (d) =>
      d.subject?.trim().toLowerCase() === subject.trim().toLowerCase() &&
      (d.grade === grade || d.grade === grade.replace("grade-", ""))
  );
  const stored = useStoredStructure(grade, subject);
  const [strands, setStrands] = React.useState<GeneratedStrand[]>([]);
  const [openStrand, setOpenStrand] = React.useState<string | null>(null);
  const [drafts, setDrafts] = React.useState<Record<string, GeneratedSubstrand[]>>({});
  const [saved, setSaved] = React.useState<Record<string, number>>({});

  // Seed from what is stored, and re-seed when the selection changes. A strand
  // generated in this session but not yet saved is kept: re-seeding must not
  // throw away work the operator has not had the chance to save.
  React.useEffect(() => {
    const data = stored.data;
    if (!data) return;
    setStrands((current) => {
      const byName = new Map<string, GeneratedStrand>();
      for (const st of data.strands) {
        byName.set(st.strand_name.toLowerCase(), {
          strand_id: st.strand_id,
          strand_name: st.strand_name,
          description: st.description,
        } as GeneratedStrand);
      }
      for (const st of current) {
        const key = strandName(st).toLowerCase();
        if (key && !byName.has(key)) byName.set(key, st);
      }
      return [...byName.values()];
    });
    setSaved(
      Object.fromEntries(
        data.strands
          .filter((st) => st.sub_strands.length > 0)
          .map((st) => [st.strand_name, st.sub_strands.length])
      )
    );
  }, [stored.data, grade, subject]);
  const [instructions, setInstructions] = React.useState("");
  // Whether the last generation actually read the KICD design, or produced a
  // plausible curriculum from the model's own knowledge.
  const [grounded, setGrounded] = React.useState<{ ok: boolean; chars: number } | null>(null);
  // What the last generation produced and could not be kept. Dropping these
  // silently is how a strand of raw page debris got saved and then had to be
  // spotted by eye.
  const [refused, setRefused] = React.useState<Refusal[]>([]);
  // Saving files each sub-strand as a version. Without a way through to it the
  // review layers exist but nobody arrives at them.
  const [filed, setFiled] = React.useState<number>(0);
  // Which strand's sub-strands were just saved, so the next step can be named
  // rather than left for the operator to find.
  const [justSaved, setJustSaved] = React.useState<string>("");

  // What a copy should contain: everything under a strand, whether it was saved
  // earlier or drafted just now. Copying `drafts` alone meant that saving —
  // which clears the draft — emptied the copy, so "Copy all" produced a list of
  // strand headings and nothing underneath, exactly when there was most to
  // check.
  const substrandsFor = React.useCallback(
    (name: string): GeneratedSubstrand[] => {
      const draft = drafts[name];
      if (draft && draft.length) return draft;
      const stored_ = (stored.data?.strands || []).find(
        (st) => st.strand_name.toLowerCase() === name.toLowerCase()
      );
      return stored_?.sub_strands || [];
    },
    [drafts, stored.data]
  );

  const allSubstrands = React.useMemo(() => {
    const map: Record<string, GeneratedSubstrand[]> = {};
    for (const st of strands) {
      const name = strandName(st);
      if (name) map[name] = substrandsFor(name);
    }
    return map;
  }, [strands, substrandsFor]);

  const busy =
    actions.generateStrands.isPending ||
    actions.generateSubstrands.isPending ||
    actions.saveSubstrands.isPending ||
    actions.saveStrands.isPending;

  async function makeStrands() {
    const res = await actions.generateStrands.mutateAsync({ custom_instructions: instructions });
    const generated = res.strands || [];
    setStrands(generated);
    setGrounded({ ok: Boolean(res.grounded), chars: res.source_chars ?? 0 });
    setRefused(res.refused || []);
    // Strands had nowhere to be stored, so the layer every sub-strand hangs
    // off vanished on reload even after its sub-strands were saved.
    if (generated.length) {
      try {
        await actions.saveStrands.mutateAsync({ strands: generated });
      } catch {
        // Generation still succeeded; the draft is on screen either way.
      }
    }
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
    setRefused(res.refused || []);
  }

  async function save(strand: GeneratedStrand) {
    const name = strandName(strand);
    const substrands = drafts[name] || [];
    if (!substrands.length) return;
    const saved = await actions.saveSubstrands.mutateAsync({
      strand_name: name,
      strand_id: strandId(strand),
      substrands,
    });
    setFiled((saved?.artifacts || []).filter((a: any) => a?.artifact_id).length);
    setSaved((s) => ({ ...s, [name]: substrands.length }));
    setJustSaved(name);
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
        {design && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setReading((v) => !v)}
            title="Read the KICD design this is generated from, by page and line"
          >
            {reading ? "Hide the design" : "Read the design"}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          disabled={busy || !subject || inspect.strands.isPending}
          title="See the document, skill and compiled prompt before generating"
          onClick={async () => setInspection(await inspect.strands.mutateAsync({ custom_instructions: instructions }))}
        >
          {inspect.strands.isPending ? "Loading…" : "Inspect prompt"}
        </Button>
        {strands.length > 0 && (
          <CopyButton
            label="Copy all"
            title="Copy every strand with its sub-strands, saved and drafted, to check in another model"
            getText={() =>
              allStrandsToText(strands, allSubstrands, { grade, subject })
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
      {justSaved && (
        <div
          style={{
            border: "1px solid var(--ok, var(--line))",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
            marginBottom: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>"{justSaved}" is saved.</strong>{" "}
          Its sub-strands are now selectable, and the production stations —
          notes, diagrams, photos and videos, simulations, activities,
          questions — open once you pick one.
          <div style={{ marginTop: "var(--s2)" }}>
            <a
              href={`/factory?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(
                subject
              )}`}
            >
              Choose a sub-strand and start producing →
            </a>
          </div>
        </div>
      )}
      {filed > 0 && (
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
            marginBottom: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          {filed} version{filed === 1 ? "" : "s"} filed for review.{" "}
          <a href={`/approvals?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(subject)}&kind=sub_strand`}>
            Review and approve them
          </a>{" "}
          — nothing is approved until an independent vendor and an approver have
          both passed it.
        </div>
      )}
      {refused.length > 0 && (
        <div
          style={{
            border: "1px solid var(--warn-border, var(--line))",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
            marginBottom: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>
            {refused.length} entr{refused.length === 1 ? "y was" : "ies were"} refused
          </strong>
          <div style={{ color: "var(--ink-3)", marginTop: 4 }}>
            The generator returned content that is raw source text or a duplicate.
            It was dropped rather than saved.
          </div>
          <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.2em" }}>
            {refused.map((r, i) => (
              <li key={i}>
                <code>{r.sub_strand_name || r.strand_name || "?"}</code> — {r.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

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
            // Saved sub-strands are shown too, not only this session's drafts.
            // Saving cleared the draft and nothing replaced it on screen, so a
            // successful save looked exactly like losing the work.
            const rows = substrandsFor(name);
            const isDraft = Boolean(draft && draft.length);
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
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    title="See the prompt that will generate this strand's sub-strands"
                    onClick={async () =>
                      setInspection(
                        await inspect.substrands.mutateAsync({
                          strand_name: name,
                          strand_id: strandId(strand),
                          custom_instructions: instructions,
                        })
                      )
                    }
                  >
                    Inspect
                  </Button>
                  <CopyButton
                    label="Copy"
                    title="Copy this strand and its sub-strands, saved or drafted"
                    getText={() => strandToText(strand, substrandsFor(name), { grade, subject })}
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

                {rows.length > 0 && (
                  <div style={{ marginTop: "var(--s3)" }}>
                    <Table
                      caption={
                        isDraft
                          ? `Sub-strands drafted for ${name} — not saved yet`
                          : `Sub-strands saved for ${name}`
                      }
                    >
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
                        {rows.map((sub, i) => (
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
                    {!isDraft && rows.length > 0 && (
                      <SubStrandVersions
                        grade={grade}
                        subject={subject}
                        names={rows.map((r) => subName(r))}
                      />
                    )}
                    {isDraft && (
                      <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s3)" }}>
                        <Button size="sm" disabled={busy} onClick={() => save(strand)}>
                          {actions.saveSubstrands.isPending
                            ? "Saving…"
                            : `Save ${draft!.length} sub-strands`}
                        </Button>
                        <Button size="sm" variant="ghost" disabled={busy} onClick={() => discard(name)}>
                          Discard
                        </Button>
                      </Stack>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </Stack>
      )}
      {reading && design && (
        <div style={{ marginBottom: "var(--s4)" }}>
          <DesignReader designId={design.design_id} />
        </div>
      )}

      <PromptInspector
        inspection={inspection}
        onClose={() => setInspection(null)}
        onAttached={async () =>
          setInspection(await inspect.strands.mutateAsync({ custom_instructions: instructions }))
        }
      />
    </Card>
  );
}
