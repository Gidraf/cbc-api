import React from "react";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  ErrorNotice,
  Input,
  QueryState,
  Select,
  Stack,
} from "../ui/components";
import { useDesignDocument, type DocLine } from "../lib/queries";

/**
 * Read a curriculum design the way a verse is cited.
 *
 * Pages come from the document itself — the extractor captures KICD's own page
 * markers — and lines are numbered within each page. That gives every line a
 * stable address, so a sub-strand or a question can record the exact lines it
 * was drawn from, and anyone reviewing it can open the page and read them.
 */

function LineRow({ line, code, highlight }: { line: DocLine; code: string; highlight?: string }) {
  const citation = `${code} ${line.ref}`;
  const parts = highlight
    ? line.text.split(new RegExp(`(${highlight.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"))
    : [line.text];

  return (
    <div
      className="doc-line"
      style={{ display: "flex", gap: "var(--s3)", alignItems: "baseline", padding: "2px 0" }}
    >
      <span
        title={citation}
        style={{
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: "var(--text-xs)",
          color: "var(--ink-3)",
          minWidth: "3.5rem",
          textAlign: "right",
          flexShrink: 0,
          userSelect: "all",
        }}
      >
        {line.page}:{line.line}
      </span>
      <span style={{ flex: 1, lineHeight: 1.7 }}>
        {parts.map((part, i) =>
          highlight && part.toLowerCase() === highlight.toLowerCase() ? (
            <mark key={i} style={{ background: "var(--accent-wash)", color: "inherit" }}>
              {part}
            </mark>
          ) : (
            <React.Fragment key={i}>{part}</React.Fragment>
          )
        )}
      </span>
      <span className="doc-line-copy" style={{ opacity: 0, flexShrink: 0 }}>
        <CopyButton
          label="Cite"
          title={`Copy "${citation}" and the line`}
          getText={() => `${citation}\n${line.text}`}
        />
      </span>
    </div>
  );
}

export function DesignReader({ designId }: { designId: string }) {
  const [page, setPage] = React.useState(1);
  const [pending, setPending] = React.useState("");
  const [query, setQuery] = React.useState("");
  const doc = useDesignDocument(designId, page, query);
  const d = doc.data;

  const lines = query ? d?.search?.hits ?? [] : d?.page_content?.lines ?? [];

  return (
    <Card
      title="The curriculum design"
      description={
        d
          ? `${d.code} · ${d.page_count} pages · ${d.line_count.toLocaleString()} lines. Every line has an address you can cite.`
          : "Read the ingested KICD document by page and line."
      }
      actions={
        <Stack direction="row" gap="var(--s2)">
          <Input
            aria-label="Search the design"
            placeholder="Search the document…"
            value={pending}
            onChange={(e) => setPending(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setQuery(pending.trim());
              if (e.key === "Escape") {
                setPending("");
                setQuery("");
              }
            }}
            style={{ width: 220 }}
          />
          {query && (
            <Button size="sm" variant="ghost" onClick={() => { setPending(""); setQuery(""); }}>
              Clear
            </Button>
          )}
          {d && !query && (
            <Select
              aria-label="Page"
              value={String(page)}
              onChange={(e) => setPage(Number(e.target.value))}
              style={{ width: "auto" }}
            >
              {d.pages.map((p) => (
                <option key={p.page} value={p.page}>
                  Page {p.page} — {p.heading.slice(0, 46)}
                </option>
              ))}
            </Select>
          )}
        </Stack>
      }
    >
      {doc.error && <ErrorNotice error={doc.error} />}
      <QueryState query={doc} label="Loading the design" rows={6} />

      {d && (
        <>
          <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s3)" }}>
            <Badge tone="info">{d.grade}</Badge>
            <Badge tone="neutral">{d.subject}</Badge>
            {query ? (
              <Badge tone={lines.length ? "ok" : "warn"}>
                {lines.length} line{lines.length === 1 ? "" : "s"} matching “{query}”
              </Badge>
            ) : (
              <Badge tone="neutral">{d.page_content?.heading}</Badge>
            )}
            <CopyButton
              label={query ? "Copy results" : "Copy this page"}
              title="Copy with the citation on every line"
              getText={() =>
                [
                  `${d.code} — ${d.subject} (${d.grade})`,
                  query ? `Search: ${query}` : `Page ${page}`,
                  "",
                  ...lines.map((l) => `${d.code} ${l.ref}  ${l.text}`),
                ].join("\n")
              }
            />
          </Stack>

          {lines.length === 0 ? (
            <EmptyState
              title={query ? "Nothing matches that" : "This page has no text"}
              description={query ? "Try a shorter phrase — search is literal." : undefined}
            />
          ) : (
            <div style={{ fontSize: "var(--text-sm)" }}>
              {lines.map((l) => (
                <LineRow
                  key={`${l.page}:${l.line}`}
                  line={l}
                  code={d.code}
                  highlight={query || undefined}
                />
              ))}
            </div>
          )}

          {!query && d.pages.length > 1 && (
            <Stack direction="row" gap="var(--s2)" justify="center" style={{ marginTop: "var(--s4)" }}>
              <Button
                size="sm"
                variant="ghost"
                disabled={page <= d.pages[0].page}
                onClick={() => {
                  const i = d.pages.findIndex((p) => p.page === page);
                  if (i > 0) setPage(d.pages[i - 1].page);
                }}
              >
                ← Previous
              </Button>
              <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", alignSelf: "center" }}>
                Page {page} of {d.page_count}
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={page >= d.pages[d.pages.length - 1].page}
                onClick={() => {
                  const i = d.pages.findIndex((p) => p.page === page);
                  if (i >= 0 && i < d.pages.length - 1) setPage(d.pages[i + 1].page);
                }}
              >
                Next →
              </Button>
            </Stack>
          )}
        </>
      )}

      <style>{`.doc-line:hover { background: var(--surface-2); }
               .doc-line:hover .doc-line-copy { opacity: 1; }`}</style>
    </Card>
  );
}
