import React from "react";
import { useSearchParams } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Field,
  Input,
  QueryState,
  Select,
  Stack,
  Table,
  Td,
  Textarea,
  Th,
} from "../ui/components";
import {
  ARTIFACT_KINDS,
  ARTIFACT_LABELS,
  useArtifact,
  useArtifactActions,
  useArtifactDiff,
  useArtifacts,
  useArtifactVersions,
  useGrades,
  useReviewVendors,
  useSubjects,
  type ArtifactLabel,
  type DimensionScore,
  type ReviewVerdict,
} from "../lib/queries";

/**
 * Versions, layered review and the approved label.
 *
 * Every generation is a version rather than an overwrite, and a label points at
 * exactly one of them — so "approved" is a fact about a specific version rather
 * than about a topic. Three layers review it: the generator's own check, an
 * independent model from a DIFFERENT vendor, then an approver. Only the third
 * can apply `approved`, and an approval resting on one vendor reviewing itself
 * is refused rather than quietly granted.
 *
 * Confidence is shown per dimension. A single "90%" says nothing about WHAT was
 * 90%: content can be beautifully written and misaligned with the design, or
 * exactly aligned and pitched at the wrong age, and both used to score in the
 * eighties.
 */

const VERDICT_TONE: Record<string, "ok" | "warn" | "danger"> = {
  pass: "ok",
  revise: "warn",
  reject: "danger",
};

const LABEL_TONE: Record<string, "ok" | "accent" | "info" | "neutral" | "danger"> = {
  approved: "ok",
  production: "accent",
  staging: "info",
  test: "neutral",
  dev: "neutral",
  rejected: "danger",
};

function scoreTone(score: number): "ok" | "warn" | "danger" {
  if (score >= 80) return "ok";
  if (score >= 60) return "warn";
  return "danger";
}

const readable = (value: string) =>
  value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** One dimension's score with the evidence behind it. A score without evidence
 *  is an opinion, and an opinion cannot be checked. */
function Dimension({ dimension }: { dimension: DimensionScore }) {
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
      <Td>
        <Badge tone={scoreTone(dimension.score)}>{dimension.score}</Badge>
      </Td>
      <Td>
        <div>{dimension.evidence || "— no evidence given —"}</div>
        {dimension.issues.length > 0 && (
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
            {dimension.issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        )}
      </Td>
    </tr>
  );
}

function ReviewCard({ review }: { review: ReviewVerdict }) {
  const dimensions = Object.values(review.dimensions || {});
  return (
    <Card
      title={`Layer ${review.layer} — ${readable(review.layer_name)}`}
      description={`${review.provider}/${review.model}${
        review.compared_with ? " · reviewed the diff against the previous version" : ""
      }`}
      actions={
        <Stack direction="row" gap="var(--s2)">
          <Badge tone={VERDICT_TONE[review.verdict] || "neutral"}>{review.verdict}</Badge>
          <Badge tone={scoreTone(review.overall_confidence)}>
            {review.overall_confidence}% overall
          </Badge>
          {review.weakest && (
            <Badge tone="warn" title="The lowest-scoring dimension">
              weakest: {readable(review.weakest)}
            </Badge>
          )}
        </Stack>
      }
    >
      <Table caption={`Confidence by dimension, layer ${review.layer}`}>
        <thead>
          <tr>
            <Th>Dimension</Th>
            <Th>Score</Th>
            <Th>Evidence</Th>
          </tr>
        </thead>
        <tbody>
          {dimensions.map((d) => (
            <Dimension key={d.name} dimension={d} />
          ))}
        </tbody>
      </Table>

      {review.issues?.length > 0 && (
        <div style={{ marginTop: "var(--s3)" }}>
          <strong style={{ fontSize: "var(--text-sm)" }}>Issues to fix</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em" }}>
            {review.issues.map((issue, i) => (
              <li key={i}>
                <Badge tone={issue.severity === "high" ? "danger" : "warn"}>
                  {issue.severity}
                </Badge>{" "}
                <strong>{issue.where}</strong> — {issue.what}
                {issue.fix && <em style={{ color: "var(--ink-3)" }}> → {issue.fix}</em>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {review.comments?.length > 0 && (
        <ul style={{ margin: "var(--s3) 0 0", paddingLeft: "1.1em", color: "var(--ink-2)" }}>
          {review.comments.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** What changed since the parent version — what a layer-2 review of a
 *  regeneration is actually about. */
function DiffPanel({ artifactId }: { artifactId: string }) {
  const diff = useArtifactDiff(artifactId);
  if (diff.isError) return null;
  if (!diff.data) return null;
  if (diff.data.identical) {
    return (
      <Card title="Nothing changed" description="This version is identical to its parent.">
        <p style={{ color: "var(--ink-3)" }}>
          Re-reviewing unchanged content produces a different score for the same
          text, which makes review look unstable when it is the reading that moved.
        </p>
      </Card>
    );
  }
  const { counts, changed, added, removed } = diff.data;
  return (
    <Card
      title="What changed since the previous version"
      description={`${counts.changed} changed · ${counts.added} added · ${counts.removed} removed`}
    >
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
              <Td>{c.was}</Td>
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
    </Card>
  );
}

function ArtifactDetail({ artifactId }: { artifactId: string }) {
  const artifact = useArtifact(artifactId);
  const actions = useArtifactActions(artifactId);
  const generatorProvider =
    String((artifact.data as any)?.provenance?.provider || "");
  const vendors = useReviewVendors(generatorProvider);
  const versions = useArtifactVersions((artifact.data as any)?.artifact_key || "");

  const [layer, setLayer] = React.useState<1 | 2 | 3>(2);
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const [comment, setComment] = React.useState("");

  // Default to a vendor that is a genuine second opinion: two models from one
  // vendor share training data and failure modes, so that pairing is one
  // opinion asked twice.
  React.useEffect(() => {
    const suggested = vendors.data?.suggested;
    if (suggested?.provider && !provider) {
      setProvider(suggested.provider);
      setModel(suggested.model || "");
    }
  }, [vendors.data, provider]);

  const chosen = vendors.data?.vendors.find((v) => v.provider === provider);
  const busy = actions.review.isPending || actions.label.isPending;

  if (artifact.isLoading || artifact.isError) {
    return <QueryState query={artifact} label="Loading the version" rows={6} />;
  }
  const data = artifact.data!;
  const approval = data.approval;

  return (
    <Stack gap="var(--s4)">
      <Card
        title={`${readable(data.kind)} · version ${data.version}`}
        description={data.artifact_id}
        actions={
          <Stack direction="row" gap="var(--s2)">
            {data.labels.map((l) => (
              <Badge key={l} tone={LABEL_TONE[l] || "neutral"}>{l}</Badge>
            ))}
            {data.labels.length === 0 && <Badge tone="neutral">unlabelled</Badge>}
          </Stack>
        }
      >
        <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
          {ARTIFACT_LABELS.map((label) => (
            <Button
              key={label}
              size="sm"
              variant={label === "approved" ? "primary" : "secondary"}
              disabled={busy || (label === "approved" && !approval.can_approve)}
              title={
                label === "approved" && !approval.can_approve
                  ? approval.blockers.join("; ")
                  : `Point the "${label}" label at this version`
              }
              onClick={() => actions.label.mutate(label as ArtifactLabel)}
            >
              {label}
            </Button>
          ))}
        </Stack>
        {actions.label.error && <ErrorNotice error={actions.label.error} />}

        {!approval.can_approve && (
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
              {approval.blockers.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
            {approval.vendors.length > 0 && (
              <div style={{ marginTop: 6, color: "var(--ink-3)" }}>
                Vendors so far: {approval.vendors.join(", ")}
              </div>
            )}
          </div>
        )}
      </Card>

      <Card
        title="Run a review layer"
        description="Layer 1 is the generator checking itself. Layer 2 is an independent second opinion, and must come from a different vendor. Only layer 3 can approve."
      >
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
              generatorProvider && provider === generatorProvider
                ? "This is the vendor that generated the content — approval will refuse it."
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
                    {v.label}
                    {v.available ? "" : " (no credentials)"}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Model">
            {(a11y) => (
              <Select {...a11y} value={model} onChange={(e) => setModel(e.target.value)}>
                {(chosen?.models || []).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </Select>
            )}
          </Field>
          <Button disabled={busy} onClick={() => actions.review.mutate({ layer, provider, model })}>
            {actions.review.isPending ? "Reviewing…" : `Run layer ${layer}`}
          </Button>
        </Stack>
        {actions.review.error && <ErrorNotice error={actions.review.error} />}
        {actions.review.data?.reviewed_a_diff && (
          <p style={{ marginTop: "var(--s2)", color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
            This is a regeneration, so the reviewer judged what changed rather
            than re-reading the whole thing.
          </p>
        )}
      </Card>

      {data.parent_artifact_id && <DiffPanel artifactId={artifactId} />}

      {data.reviews.length === 0 ? (
        <EmptyState
          title="No reviews yet"
          description="Nothing can be approved until layers 2 and 3 have run, from two different vendors."
        />
      ) : (
        data.reviews.map((r) => <ReviewCard key={r.review_id} review={r} />)
      )}

      <Card
        title="Comments"
        description="A reviewer who disagrees with a 94% needs somewhere to say so that the next approver will read. Unresolved comments are shown to every later layer."
      >
        <Stack gap="var(--s2)">
          <Textarea
            rows={3}
            value={comment}
            placeholder="What is wrong with this, and where?"
            onChange={(e) => setComment(e.target.value)}
          />
          <Stack direction="row" gap="var(--s2)">
            <Button
              size="sm"
              disabled={!comment.trim() || actions.comment.isPending}
              onClick={() =>
                actions.comment.mutate({ body: comment }, { onSuccess: () => setComment("") })
              }
            >
              {actions.comment.isPending ? "Saving…" : "Add comment"}
            </Button>
          </Stack>
          {data.comments.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "1.1em" }}>
              {data.comments.map((c) => (
                <li key={c.comment_id} style={{ opacity: c.resolved ? 0.5 : 1 }}>
                  <strong>{c.author || "someone"}</strong>: {c.body}
                  {c.resolved && <Badge tone="neutral">resolved</Badge>}
                </li>
              ))}
            </ul>
          )}
        </Stack>
      </Card>

      <Card
        title="Every attempt at this"
        description="A version is never overwritten, so a good one survives trying a better one."
      >
        <QueryState query={versions} label="Loading versions" rows={3} />
        {versions.data && (
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
              {versions.data.versions.map((v) => (
                <tr key={v.artifact_id}>
                  <Td numeric>{v.version}</Td>
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
                    {v.artifact_id !== artifactId && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          const url = new URL(window.location.href);
                          url.searchParams.set("artifact", v.artifact_id);
                          window.history.pushState({}, "", url);
                          window.dispatchEvent(new PopStateEvent("popstate"));
                        }}
                      >
                        Open
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </Stack>
  );
}

export function Approvals() {
  const [params, setParams] = useSearchParams();
  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  const kind = params.get("kind") || "";
  const label = params.get("label") || "";
  const artifactId = params.get("artifact") || "";

  const grades = useGrades();
  const subjects = useSubjects(grade);
  const artifacts = useArtifacts({ grade, subject, kind, label });

  function setParam(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v ? merged.set(k, v) : merged.delete(k)));
    setParams(merged);
  }

  if (artifactId) {
    return (
      <Stack gap="var(--s4)">
        <Button size="sm" variant="ghost" onClick={() => setParam({ artifact: "" })}>
          ← Back to all versions
        </Button>
        <ArtifactDetail artifactId={artifactId} />
      </Stack>
    );
  }

  return (
    <Stack gap="var(--s4)">
      <Card
        title="Versions and approval"
        description="Every generation is a version, never an overwrite. A label points at exactly one version, so `approved` is a fact about a specific version rather than about a topic."
      >
        <Stack direction="row" gap="var(--s3)" style={{ flexWrap: "wrap" }}>
          <Field label="Grade">
            {(a11y) => (
              <Select
                {...a11y}
                value={grade}
                onChange={(e) => setParam({ grade: e.target.value, subject: "" })}
              >
                <option value="">All grades</option>
                {(grades.data || []).map((g) => (
                  <option key={g.name} value={g.name}>{g.label || g.name}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Subject">
            {(a11y) => (
              <Select
                {...a11y}
                value={subject}
                onChange={(e) => setParam({ subject: e.target.value })}
              >
                <option value="">All subjects</option>
                {(subjects.data || []).map((s) => (
                  <option key={s.name} value={s.name}>{s.name}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Kind">
            {(a11y) => (
              <Select {...a11y} value={kind} onChange={(e) => setParam({ kind: e.target.value })}>
                <option value="">Everything</option>
                {ARTIFACT_KINDS.map((k) => (
                  <option key={k} value={k}>{readable(k)}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Label">
            {(a11y) => (
              <Select {...a11y} value={label} onChange={(e) => setParam({ label: e.target.value })}>
                <option value="">Any</option>
                {ARTIFACT_LABELS.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </Select>
            )}
          </Field>
        </Stack>
      </Card>

      <QueryState query={artifacts} label="Loading versions" rows={5} />
      {artifacts.data &&
        (artifacts.data.artifacts.length === 0 ? (
          <EmptyState
            title="Nothing here yet"
            description="Versions appear as the factory saves strands, sub-strands, notes, media prompts and questions."
          />
        ) : (
          <Card title={`${artifacts.data.count} version(s)`}>
            <Table caption="Generated versions">
              <thead>
                <tr>
                  <Th>Kind</Th>
                  <Th>Subject</Th>
                  <Th>Sub-strand</Th>
                  <Th numeric>Version</Th>
                  <Th>Status</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {artifacts.data.artifacts.map((a: any) => (
                  <tr key={a.artifact_id}>
                    <Td>{readable(a.kind)}</Td>
                    <Td>{a.subject}</Td>
                    <Td>{a.sub_strand_name || a.title || a.strand_name || "—"}</Td>
                    <Td numeric>{a.version}</Td>
                    <Td>
                      <Badge tone={a.status === "approved" ? "ok" : "neutral"}>{a.status}</Badge>
                    </Td>
                    <Td>
                      <Button size="sm" onClick={() => setParam({ artifact: a.artifact_id })}>
                        Review
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        ))}
    </Stack>
  );
}
