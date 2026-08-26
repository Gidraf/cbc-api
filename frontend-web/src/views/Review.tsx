import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  QueryState,
  PageHeader,
  Stack,
  Table,
  Td,
  Th,
  Textarea,
  useToast,
} from "../ui/components";
import { useApi } from "../lib/queries";

export function Review() {
  const api = useApi();
  const toast = useToast();
  const qc = useQueryClient();
  const [notes, setNotes] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState<string | null>(null);

  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api<any>("/api/v1/bundles?status=human_review_queue&limit=50"),
  });

  async function decide(bundleId: string, decision: "approve" | "reject") {
    setBusy(bundleId);
    try {
      await api<any>(`/api/v1/bundles/${encodeURIComponent(bundleId)}/human-decision`, {
        method: "POST",
        body: JSON.stringify({ decision, notes: notes[bundleId] || "" }),
      });
      toast(`Bundle ${decision === "approve" ? "approved" : "sent back for revision"}.`, "ok");
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      qc.invalidateQueries({ queryKey: ["progress"] });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Decision failed.", "danger");
    } finally {
      setBusy(null);
    }
  }

  const items: any[] = queue.data?.items || queue.data?.bundles || [];

  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Review queue"
        description="Bundles that cleared the automated gates and need a human decision. The measured scores that got them here are shown with each one."
        actions={
          <Button onClick={() => queue.refetch()} loading={queue.isFetching}>
            Refresh
          </Button>
        }
      />

      <QueryState query={queue} label="Loading review queue" rows={4} />

      {queue.data && items.length === 0 && (
        <EmptyState title="Queue is empty" description="Nothing is waiting on a human decision right now." />
      )}

      <Stack gap="var(--s4)">
        {items.map((bundle) => {
          const curriculum = bundle.curriculum || {};
          const audit = bundle.review_audit || {};
          const scores = audit.review?.scores || audit.scores || {};
          const questions = bundle.questions || [];
          const diagrams = bundle.diagrams || [];

          return (
            <Card
              key={bundle.bundle_id}
              title={curriculum.sub_strand || bundle.bundle_id}
              description={`${curriculum.subject || ""} · ${curriculum.grade || ""} · ${curriculum.strand || ""}`}
              actions={<Badge tone="warn">{bundle.status}</Badge>}
            >
              <Stack gap="var(--s4)">
                <Table caption="Bundle contents">
                  <thead>
                    <tr>
                      <Th>Layer</Th>
                      <Th numeric>Produced</Th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <Td>Notes</Td>
                      <Td numeric>{(bundle.notes?.hour_modules || bundle.notes?.key_concepts || []).length} modules</Td>
                    </tr>
                    <tr>
                      <Td>Diagrams</Td>
                      <Td numeric>{diagrams.length}</Td>
                    </tr>
                    <tr>
                      <Td>Activities</Td>
                      <Td numeric>{(bundle.activities || []).length}</Td>
                    </tr>
                    <tr>
                      <Td>Questions</Td>
                      <Td numeric>{questions.length}</Td>
                    </tr>
                  </tbody>
                </Table>

                {Object.keys(scores).length > 0 && (
                  <Stack direction="row" gap="var(--s2)" wrap>
                    {Object.entries(scores).map(([k, v]) => (
                      <Badge
                        key={k}
                        tone={v == null ? "neutral" : (v as number) >= 0.75 ? "ok" : (v as number) >= 0.55 ? "warn" : "danger"}
                        title={k}
                      >
                        {k.replace(/_/g, " ")} {v == null ? "pending" : (v as number).toFixed(2)}
                      </Badge>
                    ))}
                  </Stack>
                )}

                <Textarea
                  aria-label={`Reviewer notes for ${bundle.bundle_id}`}
                  placeholder="Reviewer notes — what needs changing, or why this is approved."
                  rows={3}
                  value={notes[bundle.bundle_id] || ""}
                  onChange={(e) => setNotes((n) => ({ ...n, [bundle.bundle_id]: e.target.value }))}
                />

                <Stack direction="row" gap="var(--s2)" justify="flex-end">
                  <Button
                    variant="danger"
                    loading={busy === bundle.bundle_id}
                    onClick={() => decide(bundle.bundle_id, "reject")}
                  >
                    Send back
                  </Button>
                  <Button
                    variant="primary"
                    loading={busy === bundle.bundle_id}
                    onClick={() => decide(bundle.bundle_id, "approve")}
                  >
                    Approve
                  </Button>
                </Stack>
              </Stack>
            </Card>
          );
        })}
      </Stack>
    </>
  );
}
