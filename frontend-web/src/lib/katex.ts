import katex from "katex";

/**
 * Strips wrapping $ or $$ if caller provided them, and renders via KaTeX.
 */
export function renderLatex(rawLatex: string, display: boolean = false): string {
  if (!rawLatex) return "";
  let clean = rawLatex.trim();
  if (clean.startsWith("$$") && clean.endsWith("$$")) {
    clean = clean.slice(2, -2).trim();
    display = true;
  } else if (clean.startsWith("$") && clean.endsWith("$")) {
    clean = clean.slice(1, -1).trim();
  }

  try {
    return katex.renderToString(clean, {
      displayMode: display,
      throwOnError: false,
      output: "htmlAndMathml",
    });
  } catch (err) {
    console.warn("KaTeX render error for:", rawLatex, err);
    return `<span class="katex-error" style="color:#b91c1c;font-family:monospace;">${escapeHtml(rawLatex)}</span>`;
  }
}

/**
 * Replaces $$...$$ with block math and $...$ with inline math in a text string.
 *
 * The text BETWEEN the maths is escaped. This function's output goes straight
 * into dangerouslySetInnerHTML, and its input is LLM-generated question text —
 * so passing the non-math remainder through raw meant any tag a model wrote
 * (or was talked into writing) became live markup in the console.
 *
 * Only KaTeX's own output is trusted here, because we produced it.
 */
export function renderMathInText(text: string): string {
  if (!text) return "";

  // One pass, alternating: escape the prose, render the maths. Doing it as two
  // sequential .replace() calls cannot work — the first pass would have to
  // escape text it has already turned into KaTeX markup.
  const MATH = /\$\$([\s\S]*?)\$\$|\$([^\$\n]+?)\$/g;
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = MATH.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, m.index));
    const display = m[1] !== undefined;
    out += renderLatex(display ? m[1] : m[2], display);
    last = m.index + m[0].length;
  }
  out += escapeHtml(text.slice(last));

  return out;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
