import React from "react";

import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorNotice,
  Field,
  LoadingBlock,
  Select,
  Stack,
  Table,
  Tabs,
  Td,
  Textarea,
  Th,
} from "../ui/components";
import {
  allReviewsToText,
  artifactToText,
  reviewPromptToText,
  reviewToText,
  revisionDirectivesToText,
} from "../lib/serialize";
import {
  ARTIFACT_LABELS,
  useArtifact,
  useArtifactActions,
  useArtifactDiff,
  useArtifactVersions,
  useReviewVendors,
  useRevisionDirectives,
  type ArtifactLabel,
  type DimensionScore,
  type ReviewVerdict,
} from "../lib/queries";

/**
 * Versions, layered review and the approved label, as one panel.
 *
 * These decisions belong where the work is. Sending an operator to another
 * screen to see what changed, then back to decide, made them hold the previous
 * screen in their head — so this mounts inside the Content Factory beside the
 * thing being reviewed, and the standalone screen uses the same component.
 *
 * A label points at exactly one version, so `approved` is a fact about a
 * specific version rather than about a topic. Only layer 3 can apply it, and an
 * approval resting on one vendor reviewing itself is refused: two models from
 * one vendor share training data and failure modes, so that pairing is one
 * opinion asked twice.
 */

export const VERDICT_TONE: Record<string, "ok" | "warn" | "danger"> = {
  pass: "ok",
  revise: "warn",
  reject: "danger",
};

export const LABEL_TONE: Record<string, "ok" | "accent" | "info" | "neutral" | "danger"> = {
  approved: "ok",
  production: "accent",
  staging: "info",
  test: "neutral",
  dev: "neutral",
  rejected: "danger",
};

export function scoreTone(score: number): "ok" | "warn" | "danger" {
  if (score >= 80) return "ok";
  if (score >= 60) return "warn";
  return "danger";
}

export const readable = (value: string) =>
  value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** One dimension's score with the evidence behind it. A score without evidence
 *  is an opinion, and an opinion cannot be checked. */
function DimensionRow({ dimension }: { dimension: DimensionScore }) {
  if (dimension.not_applicable) {
    return (
      <tr>
        <Td>{readable(dimension.name)}</Td>
        <Td><Badge tone="neutral">n/a</Badge></Td>
        <Td>{dimension.evidence || "Not applicable to this learning area."}</Td>
      </tr>
    );
  }
  return (
    <tr>
      <Td>{readable(dimension.name)}</Td>
      <Td><Badge tone={scoreTone(dimension.score)}>{dimension.score}</Badge></Td>
      <Td>
        <div>{dimension.evidence || "— no evidence given —"}</div>
        {dimension.issues.length > 0 && (
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
            {dimension.issues.map((issue, i) => <li key={i}>{issue}</li>)}
          </ul>
        )}
      </Td>
    </tr>
  );
}

export function ReviewCard({ review }: { review: ReviewVerdict }) {
  const dimensions = Object.values(review.dimensions || {});
  return (
    <div
      style={{
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "var(--s3)",
        marginBottom: "var(--s3)",
      }}
    >
      <Stack
        direction="row"
        gap="var(--s2)"
        style={{ flexWrap: "wrap", alignItems: "center", marginBottom: "var(--s3)" }}
      >
        <strong style={{ fontSize: "var(--text-sm)" }}>
          Layer {review.layer} — {readable(review.layer_name)}
        </strong>
        <Badge tone="neutral">{review.provider}/{review.model}</Badge>
        <Badge tone={VERDICT_TONE[review.verdict] || "neutral"}>{review.verdict}</Badge>
        <Badge tone={scoreTone(review.overall_confidence)}>
          {review.overall_confidence}% overall
        </Badge>
        {review.weakest && (
          <Badge tone="warn" title="The lowest-scoring dimension">
            weakest: {readable(review.weakest)}
          </Badge>
        )}
        {review.compared_with && (
          <Badge tone="info" title="Judged on what changed since the previous version">
            reviewed the diff
          </Badge>
        )}
        <span style={{ marginLeft: "auto" }}>
          <CopyButton
            label="Copy"
            title="Copy this verdict with the evidence behind every score, to verify it elsewhere"
            getText={() => reviewToText(review as any, {})}
          />
        </span>
      </Stack>

      <Table caption={`Confidence by dimension, layer ${review.layer}`}>
        <thead>
          <tr>
            <Th>Dimension</Th>
            <Th>Score</Th>
            <Th>Evidence</Th>
          </tr>
        </thead>
        <tbody>
          {dimensions.map((d) => <DimensionRow key={d.name} dimension={d} />)}
        </tbody>
      </Table>

      {review.issues?.length > 0 && (
        <div style={{ marginTop: "var(--s3)" }}>
          <strong style={{ fontSize: "var(--text-sm)" }}>Issues to fix</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em" }}>
            {review.issues.map((issue, i) => (
              <li key={i}>
                <Badge tone={issue.severity === "high" ? "danger" : "warn"}>{issue.severity}</Badge>{" "}
                <strong>{issue.where}</strong> — {issue.what}
                {issue.fix && <em style={{ color: "var(--ink-3)" }}> → {issue.fix}</em>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** What changed since the parent — what a layer-2 review of a regeneration is
 *  actually about. */
export function DiffTable({ artifactId, against = "" }: { artifactId: string; against?: string }) {
  const diff = useArtifactDiff(artifactId, against);

  if (diff.isLoading) return <LoadingBlock rows={3} label="Comparing versions" />;
  if (diff.isError) {
    return (
      <EmptyState
        title="Nothing to compare against"
        description="This is the first version of this artifact, so there is no previous one to diff."
      />
    );
  }
  if (!diff.data) return null;
  if (diff.data.identical) {
    return (
      <EmptyState
        title="Identical to the previous version"
        description="Re-reviewing unchanged content produces a different score for the same text, which makes review look unstable when it is the reading that moved."
      />
    );
  }

  const { counts, changed, added, removed } = diff.data;
  return (
    <>
      <Stack direction="row" gap="var(--s2)" style={{ marginBottom: "var(--s3)" }}>
        <Badge tone="warn">{counts.changed} changed</Badge>
        <Badge tone="ok">{counts.added} added</Badge>
        <Badge tone="danger">{counts.removed} removed</Badge>
      </Stack>
      <Table caption="Field-level differences">
        <thead>
          <tr>
            <Th>Field</Th>
            <Th>Was</Th>
            <Th>Now</Th>
          </tr>
        </thead>
        <tbody>
          {changed.map((c, i) => (
            <tr key={`c${i}`}>
              <Td><code>{c.path}</code></Td>
              <Td style={{ color: "var(--ink-3)" }}>{c.was}</Td>
              <Td>{c.value}</Td>
            </tr>
          ))}
          {added.map((a, i) => (
            <tr key={`a${i}`}>
              <Td><code>{a.path}</code></Td>
              <Td><Badge tone="ok">added</Badge></Td>
              <Td>{a.value}</Td>
            </tr>
          ))}
          {removed.map((r, i) => (
            <tr key={`r${i}`}>
              <Td><code>{r.path}</code></Td>
              <Td>{r.value}</Td>
              <Td><Badge tone="danger">removed</Badge></Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}

function LabelBar({
  artifactId,
  labels,
  canApprove,
  blockers,
}: {
  artifactId: string;
  labels: string[];
  canApprove: boolean;
  blockers: string[];
}) {
  const actions = useArtifactActions(artifactId);
  const [signing, setSigning] = React.useState(false);
  const [note, setNote] = React.useState("");

  return (
    <>
      <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
        {ARTIFACT_LABELS.map((label) => {
          const held = labels.includes(label);
          const blocked = label === "approved" && !canApprove;
          return (
            <Button
              key={label}
              size="sm"
              variant={held ? "primary" : "secondary"}
              disabled={actions.label.isPending || blocked}
              title={
                blocked
                  ? blockers.join("; ")
                  : held
                  ? `This version holds "${label}"`
                  : `Point "${label}" at this version`
              }
              onClick={() =>
                label === "approved"
                  ? setSigning(true)
                  : actions.label.mutate({ label: label as ArtifactLabel })
              }
            >
              {held ? `✓ ${label}` : label}
            </Button>
          );
        })}
      </Stack>

      {signing && (
        <div
          style={{
            marginTop: "var(--s3)",
            padding: "var(--s3)",
            border: "1px solid var(--accent)",
            borderRadius: "var(--radius)",
          }}
        >
          <strong style={{ fontSize: "var(--text-sm)" }}>
            You are signing for this version
          </strong>
          <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: "6px 0" }}>
            The review layers narrow what reaches you; they do not replace you.
            Approved work counts toward this grade's progress as taught-ready, so
            this is your signature under that claim.
          </p>
          <Textarea
            rows={2}
            value={note}
            placeholder="Optional: what you checked, or what you accepted despite."
            onChange={(e) => setNote(e.target.value)}
          />
          <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)" }}>
            <Button
              size="sm"
              disabled={actions.label.isPending}
              onClick={() =>
                actions.label.mutate(
                  { label: "approved", reviewed_by_me: true, note },
                  { onSuccess: () => { setSigning(false); setNote(""); } }
                )
              }
            >
              {actions.label.isPending ? "Approving…" : "I have read this — approve"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSigning(false)}>
              Cancel
            </Button>
          </Stack>
        </div>
      )}
      {actions.label.error && <ErrorNotice error={actions.label.error} />}
      {!canApprove && (
        <div
          style={{
            marginTop: "var(--s3)",
            padding: "var(--s3)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>Not approvable yet</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
            {blockers.map((b, i) => <li key={i}>{b}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}

function RunReview({
  artifactId,
  generatorProvider,
  onReviewed,
}: {
  artifactId: string;
  generatorProvider: string;
  onReviewed?: (inputs: any) => void;
}) {
  const actions = useArtifactActions(artifactId);
  const vendors = useReviewVendors(generatorProvider);
  const [layer, setLayer] = React.useState<1 | 2 | 3>(2);
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");

  // Default to a vendor that is a genuine second opinion.
  React.useEffect(() => {
    const suggested = vendors.data?.suggested;
    if (suggested?.provider && !provider) {
      setProvider(suggested.provider);
      setModel(suggested.model || "");
    }
  }, [vendors.data, provider]);

  const chosen = vendors.data?.vendors.find((v) => v.provider === provider);
  const sameVendor = Boolean(generatorProvider) && provider === generatorProvider;

  return (
    <>
      <Stack direction="row" gap="var(--s3)" style={{ flexWrap: "wrap", alignItems: "end" }}>
        <Field label="Layer">
          {(a11y) => (
            <Select
              {...a11y}
              value={String(layer)}
              onChange={(e) => setLayer(Number(e.target.value) as 1 | 2 | 3)}
            >
              <option value="1">1 — self check</option>
              <option value="2">2 — independent review</option>
              <option value="3">3 — approver</option>
            </Select>
          )}
        </Field>
        <Field
          label="Vendor"
          hint={
            sameVendor
              ? "This generated the content — two models from one vendor share failure modes, and approval will refuse it."
              : chosen?.notes
          }
        >
          {(a11y) => (
            <Select
              {...a11y}
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                const next = vendors.data?.vendors.find((v) => v.provider === e.target.value);
                setModel(next?.default || "");
              }}
            >
              <option value="">Choose a vendor…</option>
              {(vendors.data?.vendors || []).map((v) => (
                <option key={v.provider} value={v.provider} disabled={!v.available}>
                  {v.label}{v.available ? "" : " (no credentials)"}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Model">
          {(a11y) => (
            <Select {...a11y} value={model} onChange={(e) => setModel(e.target.value)}>
              {(chosen?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
            </Select>
          )}
        </Field>
        <Button
          disabled={actions.review.isPending}
          onClick={() =>
            actions.review.mutate(
              { layer, provider, model },
              { onSuccess: (res: any) => onReviewed?.(res?.inputs) }
            )
          }
        >
          {actions.review.isPending ? "Reviewing…" : `Run layer ${layer}`}
        </Button>
      </Stack>
      {actions.review.error && <ErrorNotice error={actions.review.error} />}
      {actions.review.data?.reviewed_a_diff && (
        <p style={{ marginTop: "var(--s2)", color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
          A regeneration, so the reviewer judged what changed rather than re-reading the whole thing.
        </p>
      )}
    </>
  );
}

function Comments({ artifactId, comments }: { artifactId: string; comments: any[] }) {
  const actions = useArtifactActions(artifactId);
  const [body, setBody] = React.useState("");
  return (
    <Stack gap="var(--s2)">
      <Textarea
        rows={3}
        value={body}
        placeholder="What is wrong with this, and where? Unresolved comments are shown to every later layer."
        onChange={(e) => setBody(e.target.value)}
      />
      <Stack direction="row" gap="var(--s2)">
        <Button
          size="sm"
          disabled={!body.trim() || actions.comment.isPending}
          onClick={() => actions.comment.mutate({ body }, { onSuccess: () => setBody("") })}
        >
          {actions.comment.isPending ? "Saving…" : "Add comment"}
        </Button>
      </Stack>
      {comments.length === 0 ? (
        <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>No comments yet.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: "1.1em" }}>
          {comments.map((c) => (
            <li key={c.comment_id} style={{ opacity: c.resolved ? 0.5 : 1 }}>
              <strong>{c.author || "someone"}</strong>: {c.body}
              {c.resolved && <> <Badge tone="neutral">resolved</Badge></>}
            </li>
          ))}
        </ul>
      )}
    </Stack>
  );
}

/** Regenerate carrying the reviewers' findings, rather than retyping them.
 *
 * A review that says what is wrong and then leaves a person to copy it into a
 * custom-instructions box is a review most of whose value is lost in transit. */
function Revise({ artifactId, onDone }: { artifactId: string; onDone: (id: string) => void }) {
  const directives = useRevisionDirectives(artifactId);
  const actions = useArtifactActions(artifactId);
  const [extra, setExtra] = React.useState("");

  if (directives.isLoading) return <LoadingBlock rows={3} label="Reading the findings" />;
  if (directives.isError) return <ErrorNotice error={directives.error} />;

  const found = directives.data!;
  const nothing = !found.directives;

  return (
    <Stack gap="var(--s3)">
      {nothing ? (
        <EmptyState
          title="Every reviewer passed this with no issues"
          description="There is nothing to revise. Approve it instead, or regenerate from the station to start fresh."
        />
      ) : (
        <>
          <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
            <Badge tone="danger">{found.issues.length} defect(s)</Badge>
            <Badge tone="warn">{found.weak_dimensions.length} weak dimension(s)</Badge>
            {found.human_comments.length > 0 && (
              <Badge tone="info">{found.human_comments.length} human comment(s)</Badge>
            )}
            <CopyButton
              label="Copy the instructions"
              title="Paste this into another model, or into a station's custom instructions by hand"
              getText={() => revisionDirectivesToText(found as any)}
            />
          </Stack>

          <pre
            style={{
              margin: 0,
              maxHeight: 320,
              overflow: "auto",
              fontSize: "var(--text-sm)",
              background: "var(--surface-2)",
              padding: "var(--s3)",
              borderRadius: "var(--radius-sm)",
              whiteSpace: "pre-wrap",
            }}
          >
            {found.directives}
          </pre>

          <Textarea
            rows={2}
            value={extra}
            placeholder="Optional: anything else the generator should know."
            onChange={(e) => setExtra(e.target.value)}
          />

          {!found.regeneratable ? (
            <EmptyState
              title={`A ${readable(found.kind).toLowerCase()} cannot be regenerated from here yet`}
              description="Copy the instructions above and regenerate it from its own station."
            />
          ) : (
            <Stack direction="row" gap="var(--s2)">
              <Button
                disabled={actions.regenerate.isPending}
                onClick={() =>
                  actions.regenerate.mutate(
                    { extra_instructions: extra },
                    {
                      onSuccess: (res: any) => {
                        if (res?.new_artifact?.artifact_id) onDone(res.new_artifact.artifact_id);
                      },
                    }
                  )
                }
              >
                {actions.regenerate.isPending
                  ? "Regenerating…"
                  : `Regenerate addressing ${found.issues.length} defect(s)`}
              </Button>
            </Stack>
          )}
          {actions.regenerate.error && <ErrorNotice error={actions.regenerate.error} />}
          {actions.regenerate.data && (
            <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
              Version {actions.regenerate.data.new_artifact?.version} filed from version{" "}
              {actions.regenerate.data.from_version}. Its review will read the diff
              rather than the whole thing again.
            </p>
          )}
        </>
      )}
    </Stack>
  );
}

/**
 * The whole review surface for one artifact, in tabs.
 *
 * `artifactKey` shows the version picker; pass `artifactId` alone to pin one
 * version. Selecting a version switches every tab to it, so "review the
 * changes in version 3" is one click rather than a navigation.
 */
export function VersionReview({
  artifactId,
  onSelect,
}: {
  artifactId: string;
  onSelect?: (artifactId: string) => void;
}) {
  const [picked, setPicked] = React.useState(artifactId || "");
  const [tab, setTab] = React.useState("content");
  // What the last review was actually shown. A 94% from a reviewer that was
  // never given the design is not a 94% about the curriculum, and the only way
  // to tell the two apart is to keep the inputs beside the score.
  const [lastInputs, setLastInputs] = React.useState<any>(null);

  React.useEffect(() => {
    if (artifactId) setPicked(artifactId);
  }, [artifactId]);

  const artifact = useArtifact(picked);
  // The artifact names its own key, so the sibling versions come from the
  // server's own identity rule rather than a copy of it rebuilt here.
  const versions = useArtifactVersions(artifact.data?.artifact_key || "");

  function select(id: string) {
    setPicked(id);
    onSelect?.(id);
  }

  if (!picked) {
    return (
      <EmptyState
        title="No versions yet"
        description="A version is filed each time this is generated and saved."
      />
    );
  }
  if (artifact.isLoading) return <LoadingBlock rows={4} label="Loading the version" />;
  if (artifact.isError) return <ErrorNotice error={artifact.error} />;

  const data = artifact.data!;
  const approval = data.approval;
  const rows = versions.data?.versions || [];

  const tabs = [
    { id: "content", label: "Current version", hint: "What this version actually says" },
    ...(rows.length
      ? [{
          id: "versions",
          label: "Versions",
          badge: <Badge tone="neutral">{rows.length}</Badge>,
          hint: "Every attempt, so a good one survives trying a better one",
        }]
      : []),
    {
      id: "review",
      label: "Review",
      badge: data.reviews.length ? (
        <Badge tone={approval.can_approve ? "ok" : "warn"}>{data.reviews.length}</Badge>
      ) : undefined,
      hint: "Three layers, scored per dimension",
    },
    ...(data.reviews.length
      ? [{
          id: "revise",
          label: "Regenerate",
          hint: "Generate the next version carrying the reviewers' findings",
        }]
      : []),
    ...(data.parent_artifact_id
      ? [{ id: "changes", label: "Changes", hint: "What changed since the previous version" }]
      : []),
    {
      id: "comments",
      label: "Comments",
      badge: data.comments.length ? <Badge tone="neutral">{data.comments.length}</Badge> : undefined,
    },
  ];

  return (
    <div>
      <Stack
        direction="row"
        gap="var(--s2)"
        style={{ flexWrap: "wrap", alignItems: "center", marginBottom: "var(--s3)" }}
      >
        <strong style={{ fontSize: "var(--text-sm)" }}>
          {readable(data.kind)} · version {data.version}
        </strong>
        {data.labels.map((l) => (
          <Badge key={l} tone={LABEL_TONE[l] || "neutral"}>{l}</Badge>
        ))}
        {data.labels.length === 0 && <Badge tone="neutral">unlabelled</Badge>}
      </Stack>

      <LabelBar
        artifactId={picked}
        labels={data.labels}
        canApprove={approval.can_approve}
        blockers={approval.blockers}
      />

      <div style={{ marginTop: "var(--s4)" }}>
        <Tabs tabs={tabs} active={tab} onChange={setTab} />

        {tab === "content" && (
          <Stack gap="var(--s2)">
            <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
              <CopyButton
                label={`Copy the ${readable(data.kind).toLowerCase()}`}
                title="Copy this version's content as an outline, to check it in another model"
                getText={() => artifactToText(data as any)}
              />
              <CopyButton
                label="Copy as JSON"
                title="The exact stored content, for a script or a diff"
                getText={() => JSON.stringify(data.content, null, 2)}
              />
            </Stack>
          <pre
            style={{
              margin: 0,
              maxHeight: 420,
              overflow: "auto",
              fontSize: "var(--text-sm)",
              background: "var(--surface-2)",
              padding: "var(--s3)",
              borderRadius: "var(--radius-sm)",
              whiteSpace: "pre-wrap",
            }}
          >
            {JSON.stringify(data.content, null, 2)}
          </pre>
          </Stack>
        )}

        {tab === "versions" && (
          <Table caption="Versions">
            <thead>
              <tr>
                <Th numeric>Version</Th>
                <Th>Status</Th>
                <Th>Labels</Th>
                <Th>Reviews</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.artifact_id} style={{ opacity: v.artifact_id === picked ? 1 : 0.75 }}>
                  <Td numeric>
                    {v.version}
                    {v.artifact_id === picked && <> <Badge tone="accent">viewing</Badge></>}
                  </Td>
                  <Td>{v.status}</Td>
                  <Td>
                    {(v.labels || []).map((l) => (
                      <Badge key={l} tone={LABEL_TONE[l] || "neutral"}>{l}</Badge>
                    ))}
                  </Td>
                  <Td>
                    {(v.reviews || []).map((r, i) => (
                      <Badge key={i} tone={VERDICT_TONE[r.verdict] || "neutral"}>
                        L{r.layer} {r.confidence}% {r.provider}
                      </Badge>
                    ))}
                  </Td>
                  <Td>
                    {v.artifact_id !== picked && (
                      <Button size="sm" variant="ghost" onClick={() => select(v.artifact_id)}>
                        Select
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}

        {tab === "review" && (
          <Stack gap="var(--s3)">
            <RunReview
              artifactId={picked}
              generatorProvider={String((data as any).provenance?.provider || "")}
              onReviewed={setLastInputs}
            />

            {(data.reviews.length > 0 || lastInputs) && (
              <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
                <CopyButton
                  label="Copy the review record"
                  title="Every verdict, its evidence, and what the reviewer was actually shown"
                  getText={() =>
                    allReviewsToText(data.reviews as any[], lastInputs, {
                      grade: data.grade,
                      subject: data.subject,
                      "sub strand": data.sub_strand_name,
                      version: String(data.version),
                    })
                  }
                />
                {lastInputs?.messages && (
                  <CopyButton
                    label="Copy the reviewer's prompt"
                    title="The exact messages the reviewer was sent, to reproduce this verdict in another model"
                    getText={() => reviewPromptToText(lastInputs.messages)}
                  />
                )}
              </Stack>
            )}

            {lastInputs && !lastInputs.grounding?.grounded && (
              <div
                style={{
                  border: "1px solid var(--warn, var(--line))",
                  borderRadius: "var(--radius)",
                  padding: "var(--s3)",
                  fontSize: "var(--text-sm)",
                }}
              >
                <strong>The reviewer had no design to judge against.</strong>
                <div style={{ color: "var(--ink-3)", marginTop: 4 }}>
                  {lastInputs.grounding?.missing_reason}
                </div>
                <div style={{ color: "var(--ink-3)", marginTop: 4 }}>
                  Curriculum alignment cannot be scored from this run.
                </div>
              </div>
            )}

            {lastInputs?.truncated && (
              <div
                style={{
                  border: "1px solid var(--warn, var(--line))",
                  borderRadius: "var(--radius)",
                  padding: "var(--s3)",
                  fontSize: "var(--text-sm)",
                }}
              >
                <strong>The artifact was too long to send whole.</strong>
                <div style={{ color: "var(--ink-3)", marginTop: 4 }}>
                  {lastInputs.artifact_chars.toLocaleString()} characters; the reviewer
                  saw the first 60,000 and was told so. Completeness was not scored.
                </div>
              </div>
            )}
            {data.reviews.length === 0 ? (
              <EmptyState
                title="No reviews yet"
                description="Nothing is approved until layers 2 and 3 have run, from two different vendors."
              />
            ) : (
              <div>{data.reviews.map((r) => <ReviewCard key={r.review_id} review={r} />)}</div>
            )}
          </Stack>
        )}

        {tab === "revise" && <Revise artifactId={picked} onDone={select} />}

        {tab === "changes" && <DiffTable artifactId={picked} />}

        {tab === "comments" && <Comments artifactId={picked} comments={data.comments} />}
      </div>
    </div>
  );
}
