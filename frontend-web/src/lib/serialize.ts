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
