/**
 * Turn generated content into text worth pasting into another model.
 *
 * JSON is complete but reads badly to a language model and wastes tokens on
 * punctuation; a flat summary loses the structure that makes an accuracy check
 * possible. This renders an outline: headings for keys, bullets for lists,
 * values inline — so a reviewer can paste a strand, an hour, or the whole
 * subject into a different model and ask whether it is right.
 */

const SKIP = new Set([
  "id", "_id", "uuid", "dna_id", "prompt_context", "metadata", "created_at",
  "updated_at", "usage", "model", "storage_url", "instrumented_svg",
]);

const label = (key: string) =>
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** An outline of any generated payload, readable by a person or a model. */
export function toReadable(value: unknown, depth = 0, key?: string): string {
  const pad = "  ".repeat(depth);

  if (value === null || value === undefined || value === "") return "";

  if (typeof value === "string") {
    // Long prose reads better on its own line than trailing a heading.
    return value.length > 80 ? `${pad}${key ? label(key) + ":\n" + pad : ""}${value}\n` : `${pad}${key ? label(key) + ": " : ""}${value}\n`;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return `${pad}${key ? label(key) + ": " : ""}${value}\n`;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    const head = key ? `${pad}${label(key)}:\n` : "";
    return (
      head +
      value
        .map((item) =>
          typeof item === "object" && item !== null
            ? toReadable(item, depth + 1)
            : `${"  ".repeat(depth + 1)}- ${String(item)}\n`
        )
        .join("")
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([k, v]) => !SKIP.has(k) && v !== null && v !== undefined && v !== "" &&
                 !(Array.isArray(v) && v.length === 0)
    );
    if (entries.length === 0) return "";
    const head = key ? `${pad}${label(key)}:\n` : "";
    return head + entries.map(([k, v]) => toReadable(v, key ? depth + 1 : depth, k)).join("");
  }

  return "";
}

function heading(text: string, char = "="): string {
  return `${text}\n${char.repeat(Math.min(text.length, 72))}\n`;
}

export function contextHeader(parts: Record<string, string | undefined>): string {
  const lines = Object.entries(parts)
    .filter(([, v]) => v)
    .map(([k, v]) => `${label(k)}: ${v}`);
  return lines.length ? lines.join("\n") + "\n\n" : "";
}

/** One strand and, when supplied, the sub-strands drafted under it. */
export function strandToText(
  strand: Record<string, any>,
  substrands: Record<string, any>[] | undefined,
  context: Record<string, string | undefined> = {}
): string {
  const name = strand.strand_name || strand.name || "Strand";
  let out = contextHeader(context) + heading(name);
  if (strand.description) out += `${strand.description}\n`;
  out += "\n";

  (substrands || []).forEach((s, i) => {
    const title = s.sub_strand_name || s.name || `Sub-strand ${i + 1}`;
    out += heading(`${i + 1}. ${title}`, "-");
    out += toReadable(s);
    out += "\n";
  });

  return out.trimEnd() + "\n";
}

/** Every strand with its sub-strands, for checking a whole subject at once. */
export function allStrandsToText(
  strands: Record<string, any>[],
  draftsByStrand: Record<string, Record<string, any>[]>,
  context: Record<string, string | undefined> = {}
): string {
  const header = contextHeader(context) + heading("CURRICULUM STRUCTURE") + "\n";
  return (
    header +
    strands
      .map((s) => strandToText(s, draftsByStrand[s.strand_name || s.name || ""], {}))
      .join("\n")
  );
}

/** One hour module with the assets planned against it. */
export function hourToText(
  hour: Record<string, any>,
  visuals: Record<string, any>[],
  activities: Record<string, any>[],
  context: Record<string, string | undefined> = {}
): string {
  let out = contextHeader(context) + heading(hour.hour_title || `Hour ${hour.hour_index}`);
  out += toReadable(hour) + "\n";

  if (visuals.length) {
    out += heading("Visuals for this hour", "-") + toReadable(visuals) + "\n";
  }
  if (activities.length) {
    out += heading("Experiments and activities for this hour", "-") + toReadable(activities) + "\n";
  }
  return out.trimEnd() + "\n";
}

/** Every hour of a sub-strand, with its assets. */
export function allHoursToText(
  hours: Record<string, any>[],
  visualsFor: (h: number) => Record<string, any>[],
  activitiesFor: (h: number) => Record<string, any>[],
  context: Record<string, string | undefined> = {}
): string {
  return (
    contextHeader(context) +
    heading("LESSON NOTES AND ASSETS, HOUR BY HOUR") +
    "\n" +
    hours
      .map((h) =>
        hourToText(h, visualsFor(h.hour_index), activitiesFor(h.hour_index), {})
      )
      .join("\n")
  );
}

/** Anything a station returned, with its context, ready to paste. */
export function stationToText(
  station: string,
  result: unknown,
  context: Record<string, string | undefined> = {}
): string {
  return contextHeader(context) + heading(station.toUpperCase()) + toReadable(result);
}


/** One review verdict, with the evidence behind every score.
 *
 * A verdict is only checkable if the scores travel with what they were based
 * on. Copying "94%" tells the next reader nothing they can verify. */
export function reviewToText(
  review: Record<string, any>,
  context: Record<string, string | undefined> = {}
): string {
  let out = contextHeader(context);
  out += heading(`LAYER ${review.layer} — ${label(review.layer_name || "review")}`);
  out += `Reviewer: ${review.provider}/${review.model}\n`;
  out += `Verdict: ${review.verdict} at ${review.overall_confidence}% overall\n`;
  if (review.weakest) out += `Weakest dimension: ${label(review.weakest)}\n`;
  if (review.compared_with) out += `Judged as a diff against ${review.compared_with}\n`;
  out += "\n";

  const dims: any[] = Object.values(review.dimensions || {});
  if (dims.length) {
    out += heading("Confidence by dimension", "-");
    for (const d of dims) {
      out += d.not_applicable
        ? `${label(d.name)}: not applicable — ${d.evidence || "no reason given"}\n`
        : `${label(d.name)}: ${d.score}/100\n  Evidence: ${d.evidence || "— none given —"}\n`;
      for (const issue of d.issues || []) out += `  - ${issue}\n`;
      out += "\n";
    }
  }

  if (review.issues?.length) {
    out += heading("Issues to fix", "-");
    for (const i of review.issues) {
      out += `[${i.severity}] ${i.where}: ${i.what}${i.fix ? ` -> ${i.fix}` : ""}\n`;
    }
    out += "\n";
  }

  if (review.comments?.length) {
    out += heading("Reviewer comments", "-");
    for (const c of review.comments) out += `- ${c}\n`;
  }

  return out.trimEnd() + "\n";
}

/** Every review of one version, plus what the reviewers were actually shown.
 *
 * The inputs matter as much as the scores: a 94% from a reviewer that was never
 * given the design is not a 94% about the curriculum. */
export function allReviewsToText(
  reviews: Record<string, any>[],
  inputs: Record<string, any> | undefined,
  context: Record<string, string | undefined> = {}
): string {
  let out = contextHeader(context) + heading("REVIEW RECORD") + "\n";

  if (inputs) {
    out += heading("What the reviewer was shown", "-");
    const g = inputs.grounding || {};
    out += `Design available: ${g.grounded ? `yes (${g.source}, ${g.chars} chars)` : "NO"}\n`;
    if (!g.grounded && g.missing_reason) out += `Why not: ${g.missing_reason}\n`;
    out += `Artifact: ${inputs.artifact_chars} chars${inputs.truncated ? " (TRUNCATED)" : ""}\n`;
    out += `Prior reviews shown: ${inputs.prior_reviews}\n`;
    out += `Human comments shown: ${inputs.human_comments}\n`;
    out += `Total prompt: ${inputs.prompt_chars} chars\n\n`;
  }

  out += reviews.map((r) => reviewToText(r, {})).join("\n");
  return out.trimEnd() + "\n";
}

/** The exact messages sent to the reviewer, for reproducing a verdict elsewhere. */
export function reviewPromptToText(messages: { role: string; content: string }[]): string {
  return messages
    .map((m) => `${heading(m.role.toUpperCase(), "-")}${m.content}`)
    .join("\n\n");
}


/** Any artifact's own content, laid out for a person or another model.
 *
 * One reader for every kind, so a photo prompt copies as readably as a set of
 * notes. Copying raw JSON makes a reviewer parse punctuation to find the thing
 * they were checking. */
export function artifactToText(
  artifact: Record<string, any>,
  context: Record<string, string | undefined> = {}
): string {
  const kind = String(artifact.kind || "artifact");
  let out = contextHeader({
    grade: artifact.grade,
    subject: artifact.subject,
    strand: artifact.strand_name,
    "sub strand": artifact.sub_strand_name,
    kind,
    version: artifact.version ? `${artifact.version}` : undefined,
    labels: (artifact.labels || []).join(", ") || undefined,
    ...context,
  });
  out += heading(String(artifact.title || artifact.sub_strand_name || kind).toUpperCase());

  const content = artifact.content || {};
  // A few kinds carry one obvious list; render that as an outline rather than
  // as a nested object, which is what makes it checkable at a glance.
  const listKey = ["strands", "sub_strands", "visuals", "activities", "experiments",
                   "questions", "photo_prompts", "video_prompts", "hour_modules"]
    .find((k) => Array.isArray(content[k]) && content[k].length);

  if (listKey) {
    const items: any[] = content[listKey];
    out += `${label(listKey)}: ${items.length}\n\n`;
    items.forEach((item, i) => {
      const title =
        item?.strand_name || item?.sub_strand_name || item?.name || item?.title ||
        item?.hour_title || item?.question || `${label(listKey)} ${i + 1}`;
      out += heading(`${i + 1}. ${title}`, "-");
      out += toReadable(item);
      out += "\n";
    });
    const rest = Object.fromEntries(
      Object.entries(content).filter(([k]) => k !== listKey)
    );
    if (Object.keys(rest).length) out += heading("Other fields", "-") + toReadable(rest);
  } else {
    out += toReadable(content);
  }

  return out.trimEnd() + "\n";
}

/** What a regeneration would be told to fix. Copyable so the same instruction
 *  can be pasted into another model, or into a station by hand. */
export function revisionDirectivesToText(
  revision: Record<string, any>,
  context: Record<string, string | undefined> = {}
): string {
  let out = contextHeader(context) + heading("WHAT THE REVIEWERS ASKED FOR");
  out += `${(revision.issues || []).length} defect(s), `;
  out += `${(revision.weak_dimensions || []).length} weak dimension(s), `;
  out += `${(revision.human_comments || []).length} human comment(s)\n\n`;
  out += String(revision.directives || "No findings — nothing to revise.");
  return out.trimEnd() + "\n";
}
