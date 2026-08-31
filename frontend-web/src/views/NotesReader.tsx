import React from "react";
import { Badge, Button, Card, CopyButton, EmptyState, Stack } from "../ui/components";
import { toReadable } from "../lib/serialize";
import { hourModulesOf, type HourModule } from "../lib/queries";

/**
 * The teacher's guide, as a document a teacher can read.
 *
 * The console could produce notes, score them, review them and approve them,
 * and never once show them as prose. The only way to read what had been
 * written was to open the raw JSON — which is how a lesson taught three times
 * under three titles, and an out-of-design story in lesson 4, both survived
 * several reviews: nobody had read the thing end to end, because there was
 * nowhere to read it.
 *
 * So this renders the guide the way it will actually be used: the lessons in
 * order, each one's topics in the order the children live through them, the
 * teacher's own words, and the handover between topics that says how one leads
 * to the next.
 */

function Segment({ segment, index }: { segment: any; index: number }) {
  return (
    <div style={{ marginBottom: "var(--s4)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--s2)",
          marginBottom: "var(--s2)",
        }}
      >
        <span
          className="mono"
          style={{ color: "var(--ink-3)", fontSize: "0.8em", minWidth: "1.4rem" }}
        >
          {index + 1}.
        </span>
        <strong style={{ fontSize: "var(--text-md)" }}>
          {segment.topic || `Part ${index + 1}`}
        </strong>
        {segment.minutes ? (
          <span className="mono" style={{ color: "var(--ink-3)", fontSize: "0.8em" }}>
            {segment.minutes} min
          </span>
        ) : null}
      </div>
      <p style={{ margin: "0 0 var(--s2) 1.9rem", lineHeight: 1.65 }}>{segment.body}</p>
      {segment.bridge && (
        <p
          style={{
            margin: "0 0 0 1.9rem",
            paddingLeft: "var(--s3)",
            borderLeft: "2px solid var(--line)",
            color: "var(--ink-2)",
            fontStyle: "italic",
          }}
        >
          {segment.bridge}
        </p>
      )}
    </div>
  );
}

function Aside({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: "var(--s3)" }}>
      <div
        style={{
          fontSize: "var(--text-sm)",
          fontWeight: 600,
          color: "var(--ink-2)",
          marginBottom: "4px",
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", lineHeight: 1.6 }}>
        {children}
      </div>
    </div>
  );
}

function Lesson({ module, n }: { module: HourModule & any; n: number }) {
  const segments: any[] = module.exposition_segments || [];
  const misconceptions: any[] = module.common_misconceptions || [];
  const d = module.differentiation || {};

  return (
    <article
      style={{
        borderTop: "1px solid var(--line)",
        paddingTop: "var(--s4)",
        marginTop: "var(--s4)",
      }}
    >
      <header style={{ marginBottom: "var(--s3)" }}>
        <h3 style={{ margin: 0, fontSize: "var(--text-lg)" }}>
          {module.title || `Lesson ${n}`}
        </h3>
        <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: "var(--s2)" }}>
          {module.duration_minutes ? (
            <Badge tone="neutral">{module.duration_minutes} minutes</Badge>
          ) : null}
          {(module.slos_covered || []).map((s: string, i: number) => (
            <Badge key={i} tone="neutral">
              {s}
            </Badge>
          ))}
        </Stack>
        {module.learning_intent && (
          <p style={{ margin: "var(--s2) 0 0", color: "var(--ink-2)" }}>
            <strong style={{ color: "var(--ink-1)" }}>By the end:</strong>{" "}
            {module.learning_intent}
          </p>
        )}
      </header>

      {segments.length > 0 ? (
        segments.map((s, i) => <Segment key={i} segment={s} index={i} />)
      ) : (
        <p style={{ color: "var(--ink-2)", lineHeight: 1.65 }}>
          {module.teacher_exposition || "No teaching content was written for this lesson."}
        </p>
      )}

      {(module.key_questions || []).length > 0 && (
        <Aside title="Ask, in this order">
          <ol style={{ margin: 0, paddingLeft: "1.1rem" }}>
            {module.key_questions.map((q: string, i: number) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </Aside>
      )}

      {(module.resources_needed || []).length > 0 && (
        <Aside title="Have ready">{module.resources_needed.join(" · ")}</Aside>
      )}

      {misconceptions.length > 0 && (
        <Aside title="What goes wrong">
          {misconceptions.map((m: any, i: number) => (
            <p key={i} style={{ margin: "0 0 var(--s2)" }}>
              <strong>{m.misconception}</strong>
              {m.why_it_happens ? ` — ${m.why_it_happens}` : ""}
              {m.how_to_correct_it ? ` Correct it by: ${m.how_to_correct_it}` : ""}
            </p>
          ))}
        </Aside>
      )}

      {(d.struggling || d.confident || d.sne) && (
        <Aside title="If a learner is stuck, ahead, or needs support">
          {d.struggling && <p style={{ margin: 0 }}>Stuck: {d.struggling}</p>}
          {d.confident && <p style={{ margin: 0 }}>Ahead: {d.confident}</p>}
          {d.sne && <p style={{ margin: 0 }}>Special needs: {d.sne}</p>}
        </Aside>
      )}

      {module.formative_check && (
        <Aside title="How you know it worked">{module.formative_check}</Aside>
      )}

      {module.homework_or_follow_up && (
        <Aside title="After the lesson">{module.homework_or_follow_up}</Aside>
      )}
    </article>
  );
}

export function NotesReader({
  notes,
  subStrand,
  version = 0,
}: {
  notes: any;
  subStrand: string;
  /** Non-zero when this is a version read back from the store rather than the
   *  output of the run that is on screen. */
  version?: number;
}) {
  const modules = hourModulesOf(notes);

  if (!modules.length) {
    return (
      <EmptyState
        title="No lessons to read"
        description="The guide has no modules in it yet. Generate the notes and they appear here as a document."
      />
    );
  }

  return (
    <Card
      title="Read the guide"
      description={
        `${modules.length} lesson${modules.length === 1 ? "" : "s"} for ${subStrand}` +
        (version ? ` · saved version ${version}` : "")
      }
      actions={
        <Stack direction="row" gap="var(--s2)">
          <CopyButton getText={() => toReadable(notes)} label="Copy as text" />
          <Button size="sm" variant="ghost" onClick={() => window.print()}>
            Print
          </Button>
        </Stack>
      }
    >
      <div style={{ maxWidth: "68ch" }}>
        {notes?.intro && (
          <p style={{ margin: "0 0 var(--s3)", lineHeight: 1.65, color: "var(--ink-2)" }}>
            {notes.intro}
          </p>
        )}

        {(notes?.gaps || []).length > 0 && (
          <div
            style={{
              border: "1px solid var(--warn)",
              background: "var(--warn-wash)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
              fontSize: "var(--text-sm)",
            }}
          >
            <strong>What the design did not supply</strong>
            <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.1rem" }}>
              {notes.gaps.map((g: string, i: number) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          </div>
        )}

        {modules.map((m: any, i: number) => (
          <Lesson key={i} module={m} n={i + 1} />
        ))}
      </div>
    </Card>
  );
}
