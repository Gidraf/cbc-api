import React from "react";
import { useSearchParams } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  QueryState,
  Select,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { ARTIFACT_KINDS, ARTIFACT_LABELS, useArtifacts, useGrades, useSubjects } from "../lib/queries";
import { VersionReview, readable } from "./VersionReview";

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
        <Card title="Version review">
          <VersionReview artifactId={artifactId} />
        </Card>
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
