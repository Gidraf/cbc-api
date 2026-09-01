import React from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  LoadingBlock,
  QueryState,
  PageHeader,
  Select,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { apiUrl } from "../api";
import { gradeOptionLabel, useExams, useGrades } from "../lib/queries";

/**
 * Composed papers. Rendering opens the print-ready HTML in a new tab, where the
 * browser's own print dialog produces the PDF — diagrams are inlined as SVG, so
 * nothing depends on the printer being able to fetch an asset.
 */
export function ExamBuilder() {
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const exams = useExams({ grade: grade || undefined });

  function renderUrl(examId: string, opts: { answers?: boolean; format?: string; download?: boolean } = {}) {
    const params = new URLSearchParams({ format: opts.format || "html" });
    if (opts.answers) params.set("include_answers", "true");
    if (opts.download) params.set("download", "true");
    return apiUrl(`/api/v1/exams/${encodeURIComponent(examId)}/render?${params}`);
  }

  return (
    <>
      <PageHeader
        eyebrow="Assess"
        title="Exam builder"
        description="Papers composed from approved questions. Each one records the exact question versions it contains, so a reprint is identical to the original."
        actions={
          <Select aria-label="Grade" value={grade} onChange={(e) => setGrade(e.target.value)} style={{ width: "auto" }}>
            <option value="">All grades</option>
            {(grades.data || []).map((g) => (
              <option key={g.slug || g.name} value={g.slug || g.name}>
                {gradeOptionLabel(g)}
              </option>
            ))}
          </Select>
        }
      />

      <QueryState query={exams} label="Loading exams" rows={4} />

      {exams.data && exams.data.items.length === 0 && (
        <EmptyState
          title="No papers composed yet"
          description="Select questions in the question bank and compose them into a paper."
          action={
            <Link to="/questions">
              <Button variant="primary">Open question bank</Button>
            </Link>
          }
        />
      )}

      {exams.data && exams.data.items.length > 0 && (
        <Card padded={false}>
          <Table caption="Composed exams">
            <thead>
              <tr>
                <Th>Title</Th>
                <Th>Grade</Th>
                <Th>Subject</Th>
                <Th numeric>Questions</Th>
                <Th numeric>Marks</Th>
                <Th>Time</Th>
                <Th>Output</Th>
              </tr>
            </thead>
            <tbody>
              {exams.data.items.map((exam: any) => (
                <tr key={exam.exam_id}>
                  <Td>
                    <strong>{exam.title}</strong>
                    <div className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                      {exam.exam_id}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone="neutral">{exam.grade_label || exam.grade}</Badge>
                  </Td>
                  <Td>{exam.subject}</Td>
                  <Td numeric>{exam.question_ids?.length ?? 0}</Td>
                  <Td numeric>{exam.total_marks}</Td>
                  <Td>{exam.time_allowed}</Td>
                  <Td>
                    <Stack direction="row" gap="var(--s1)" wrap>
                      <Button size="sm" onClick={() => window.open(renderUrl(exam.exam_id), "_blank")}>
                        Paper
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => window.open(renderUrl(exam.exam_id, { answers: true }), "_blank")}
                      >
                        Paper + scheme
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          window.open(renderUrl(exam.exam_id, { answers: true, format: "markdown", download: true }), "_blank")
                        }
                      >
                        Markdown
                      </Button>
                    </Stack>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card title="Consuming these from your own exam builder" accent="info">
        <Stack gap="var(--s3)">
          <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", maxWidth: "68ch" }}>
            The public API serves approved questions in curriculum order — PP1 through Grade 12, then DTE —
            with answers, marking schemes, four-level rubrics and full DNA lineage. Superseded versions are
            excluded, so a caller always receives the current text.
          </p>
          <pre
            style={{
              background: "var(--surface-2)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
              fontSize: "var(--text-xs)",
              overflowX: "auto",
              margin: 0,
            }}
          >
{`GET /api/v1/public/questions?grade=grade-7&subject=Integrated%20Science
GET /api/v1/public/questions/{question_id}
GET /api/v1/public/grades

# Diagram variants — strip the label layer for the paper, keep it for the key
GET /api/v1/public/diagrams/{diagram_id}
GET /api/v1/public/diagrams/{diagram_id}/render?hide_layers=labels
GET /api/v1/public/diagrams/{diagram_id}/render?region_id=upper_section

# Compose and print
POST /api/v1/exams
GET  /api/v1/exams/{exam_id}/render?format=html&include_answers=true`}
          </pre>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
            Authenticate with <code>x-api-key</code>. Create keys from the advanced console.
          </p>
        </Stack>
      </Card>
    </>
  );
}
