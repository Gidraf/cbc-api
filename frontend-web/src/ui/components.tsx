/**
 * Shared UI primitives.
 *
 * Everything here reads its colours from the tokens in tokens.css, so a theme
 * change is one file rather than a search across 1,287 inline style objects.
 * Interactive elements carry the ARIA the previous console had none of.
 */
import React from "react";

/* ── Layout ─────────────────────────────────────────────────────────────── */

export function Stack({
  gap = "var(--s4)",
  direction = "column",
  align,
  justify,
  wrap,
  style,
  children,
  ...rest
}: {
  gap?: string;
  direction?: "row" | "column";
  align?: string;
  justify?: string;
  wrap?: boolean;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: direction,
        gap,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? "wrap" : undefined,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function Grid({
  min = "260px",
  gap = "var(--s4)",
  style,
  children,
  ...rest
}: { min?: string; gap?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${min}, 1fr))`,
        gap,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <header
      style={{
        display: "flex",
        gap: "var(--s4)",
        alignItems: "flex-start",
        justifyContent: "space-between",
        flexWrap: "wrap",
        paddingBottom: "var(--s4)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)", minWidth: "16rem" }}>
        {eyebrow && <Label>{eyebrow}</Label>}
        <h1>{title}</h1>
        {description && (
          <p style={{ color: "var(--ink-2)", maxWidth: "62ch", fontSize: "var(--text-sm)" }}>{description}</p>
        )}
      </div>
      {actions && <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>{actions}</div>}
    </header>
  );
}

export function Label({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <span
      style={{
        fontSize: "var(--text-xs)",
        fontWeight: 600,
        letterSpacing: "0.09em",
        textTransform: "uppercase",
        color: "var(--ink-3)",
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/* ── Card ───────────────────────────────────────────────────────────────── */

export function Card({
  title,
  description,
  actions,
  footer,
  padded = true,
  accent,
  children,
  style,
  ...rest
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  padded?: boolean;
  accent?: "ok" | "warn" | "danger" | "info" | "accent";
  // `title` is deliberately widened from the HTML attribute so a card heading
  // can carry badges and status alongside its text.
} & Omit<React.HTMLAttributes<HTMLDivElement>, "title">) {
  return (
    <section
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        borderTop: accent ? `3px solid var(--${accent})` : undefined,
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow-1)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        ...style,
      }}
      {...rest}
    >
      {(title || actions) && (
        <div
          style={{
            display: "flex",
            gap: "var(--s3)",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "var(--s3) var(--s4)",
            borderBottom: "1px solid var(--line-2)",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 }}>
            {typeof title === "string" ? <h3>{title}</h3> : title}
            {description && (
              <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{description}</span>
            )}
          </div>
          {actions && <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>{actions}</div>}
        </div>
      )}
      <div style={{ padding: padded ? "var(--s4)" : 0, flex: 1, minWidth: 0 }}>{children}</div>
      {footer && (
        <div
          style={{
            padding: "var(--s3) var(--s4)",
            borderTop: "1px solid var(--line-2)",
            background: "var(--surface-2)",
            fontSize: "var(--text-sm)",
          }}
        >
          {footer}
        </div>
      )}
    </section>
  );
}

/* ── Button ─────────────────────────────────────────────────────────────── */

type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  disabled,
  children,
  style,
  ...rest
}: ButtonProps) {
  const palette: Record<string, React.CSSProperties> = {
    primary: { background: "var(--accent)", color: "var(--accent-ink)", borderColor: "var(--accent)" },
    secondary: { background: "var(--surface)", color: "var(--ink)", borderColor: "var(--line)" },
    ghost: { background: "transparent", color: "var(--ink-2)", borderColor: "transparent" },
    danger: { background: "var(--danger-wash)", color: "var(--danger)", borderColor: "var(--danger)" },
  };

  const isDisabled = disabled || loading;

  return (
    <button
      type="button"
      disabled={isDisabled}
      aria-busy={loading || undefined}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--s2)",
        padding: size === "sm" ? "5px 10px" : "8px 14px",
        fontSize: size === "sm" ? "var(--text-sm)" : "var(--text-md)",
        fontWeight: 550,
        borderRadius: "var(--radius-sm)",
        borderWidth: 1,
        borderStyle: "solid",
        cursor: isDisabled ? "not-allowed" : "pointer",
        opacity: isDisabled ? 0.55 : 1,
        transition: "background 0.12s ease, border-color 0.12s ease",
        whiteSpace: "nowrap",
        ...palette[variant],
        ...style,
      }}
      {...rest}
    >
      {loading ? <Spinner size={size === "sm" ? 12 : 14} /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: size,
        height: size,
        border: "2px solid currentColor",
        borderTopColor: "transparent",
        borderRadius: "50%",
        animation: "cbc-spin 0.7s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}

/* ── Badge ──────────────────────────────────────────────────────────────── */

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: "neutral" | "ok" | "warn" | "danger" | "info" | "accent";
  children: React.ReactNode;
  title?: string;
}) {
  const map: Record<string, [string, string]> = {
    neutral: ["var(--surface-2)", "var(--ink-2)"],
    ok: ["var(--ok-wash)", "var(--ok)"],
    warn: ["var(--warn-wash)", "var(--warn)"],
    danger: ["var(--danger-wash)", "var(--danger)"],
    info: ["var(--info-wash)", "var(--info)"],
    accent: ["var(--accent-wash)", "var(--accent)"],
  };
  const [bg, fg] = map[tone];
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        background: bg,
        color: fg,
        fontSize: "var(--text-xs)",
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: "999px",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/* ── Progress ───────────────────────────────────────────────────────────── */

export function ProgressBar({
  value,
  tone,
  height = 8,
  label,
}: {
  value: number;
  tone?: "ok" | "warn" | "danger" | "accent";
  height?: number;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  const auto = pct >= 90 ? "ok" : pct >= 50 ? "accent" : pct >= 25 ? "warn" : "danger";
  const color = `var(--${tone || auto})`;

  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      style={{
        background: "var(--surface-3)",
        borderRadius: 999,
        height,
        overflow: "hidden",
        width: "100%",
      }}
    >
      <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s ease" }} />
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone,
  progress,
  estimated,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "ok" | "warn" | "danger" | "accent";
  progress?: number;
  estimated?: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "var(--s3) var(--s4) var(--s4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s2)",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s2)", justifyContent: "space-between" }}>
        <Label>{label}</Label>
        {estimated && (
          <Badge tone="warn" title="Requirement estimated because the curriculum blueprint did not specify it">
            estimated
          </Badge>
        )}
      </div>
      <span
        style={{
          fontSize: "var(--text-2xl)",
          fontWeight: 650,
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          color: tone ? `var(--${tone})` : "var(--ink)",
        }}
      >
        {value}
      </span>
      {progress !== undefined && <ProgressBar value={progress} tone={tone} label={label} />}
      {sub && <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{sub}</span>}
    </div>
  );
}

/* ── Form fields ────────────────────────────────────────────────────────── */

let fieldSeq = 0;

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => React.ReactNode;
}) {
  const id = React.useMemo(() => `f${++fieldSeq}`, []);
  const describedBy = hint || error ? `${id}-desc` : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)", minWidth: 0 }}>
      <label htmlFor={id} style={{ fontSize: "var(--text-sm)", fontWeight: 550, color: "var(--ink-2)" }}>
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {(hint || error) && (
        <span
          id={describedBy}
          style={{ fontSize: "var(--text-xs)", color: error ? "var(--danger)" : "var(--ink-3)" }}
        >
          {error || hint}
        </span>
      )}
    </div>
  );
}

const controlStyle: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  borderRadius: "var(--radius-sm)",
  padding: "7px 10px",
  fontSize: "var(--text-md)",
  width: "100%",
  minWidth: 0,
};

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ style, ...rest }, ref) {
    return <select ref={ref} style={{ ...controlStyle, ...style }} {...rest} />;
  }
);

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ style, ...rest }, ref) {
    return <input ref={ref} style={{ ...controlStyle, ...style }} {...rest} />;
  }
);

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ style, ...rest }, ref) {
    return <textarea ref={ref} style={{ ...controlStyle, resize: "vertical", ...style }} {...rest} />;
  }
);

/* ── States ─────────────────────────────────────────────────────────────── */

export function Skeleton({ height = 16, width = "100%" }: { height?: number | string; width?: number | string }) {
  return (
    <div
      aria-hidden="true"
      style={{
        height,
        width,
        borderRadius: "var(--radius-sm)",
        background:
          "linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 50%, var(--surface-2) 75%)",
        backgroundSize: "800px 100%",
        animation: "cbc-shimmer 1.4s linear infinite",
      }}
    />
  );
}

export function LoadingBlock({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }} aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={i === 0 ? 22 : 14} width={i === 0 ? "45%" : "100%"} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  tone = "neutral",
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  tone?: "neutral" | "warn" | "danger";
}) {
  const border =
    tone === "danger" ? "var(--danger)" : tone === "warn" ? "var(--warn)" : "var(--line)";
  return (
    <div
      style={{
        border: `1px dashed ${border}`,
        borderRadius: "var(--radius)",
        padding: "var(--s6) var(--s5)",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s3)",
        alignItems: "center",
        background: tone === "danger" ? "var(--danger-wash)" : tone === "warn" ? "var(--warn-wash)" : "transparent",
      }}
    >
      <h3 style={{ color: tone === "danger" ? "var(--danger)" : "var(--ink)" }}>{title}</h3>
      {description && (
        <p style={{ color: "var(--ink-2)", fontSize: "var(--text-sm)", maxWidth: "52ch" }}>{description}</p>
      )}
      {action}
    </div>
  );
}

/**
 * Renders the loading and error states of a query, and nothing at all when the
 * query is disabled because a prerequisite is missing.
 *
 * That last case matters: a disabled TanStack query reports `isPending` forever,
 * so guarding on `isPending` alone leaves a skeleton on screen permanently when
 * the thing it depends on has not been chosen yet.
 */
export function QueryState({
  query,
  label,
  rows = 4,
  idle,
}: {
  query: {
    isLoading: boolean;
    isError: boolean;
    isPending: boolean;
    fetchStatus: string;
    error: unknown;
    refetch: () => unknown;
  };
  label: string;
  rows?: number;
  idle?: React.ReactNode;
}) {
  const disabled = query.isPending && query.fetchStatus === "idle";
  if (disabled) return <>{idle ?? null}</>;
  if (query.isLoading) return <LoadingBlock rows={rows} label={label} />;
  if (query.isError) return <ErrorNotice error={query.error} onRetry={() => query.refetch()} />;
  return null;
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof Error ? error.message : typeof error === "string" ? error : "Something went wrong.";
  return (
    <div
      role="alert"
      style={{
        border: "1px solid var(--danger)",
        background: "var(--danger-wash)",
        borderRadius: "var(--radius)",
        padding: "var(--s4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s3)",
        alignItems: "flex-start",
      }}
    >
      <strong style={{ color: "var(--danger)" }}>Could not load this</strong>
      <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/* ── Table ──────────────────────────────────────────────────────────────── */

export function Table({ children, caption }: { children: React.ReactNode; caption?: string }) {
  return (
    <div className="scroll-x" style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}

export function Th({ children, numeric }: { children?: React.ReactNode; numeric?: boolean }) {
  return (
    <th
      scope="col"
      style={{
        textAlign: numeric ? "right" : "left",
        padding: "var(--s2) var(--s3)",
        background: "var(--surface-2)",
        borderBottom: "1px solid var(--line)",
        fontSize: "var(--text-xs)",
        fontWeight: 650,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: "var(--ink-3)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  numeric,
  style,
}: {
  children: React.ReactNode;
  numeric?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <td
      style={{
        padding: "var(--s2) var(--s3)",
        borderBottom: "1px solid var(--line-2)",
        textAlign: numeric ? "right" : "left",
        fontVariantNumeric: numeric ? "tabular-nums" : undefined,
        verticalAlign: "top",
        ...style,
      }}
    >
      {children}
    </td>
  );
}

/* ── Modal ──────────────────────────────────────────────────────────────── */

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = "min(920px, 94vw)",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // Move focus into the dialog so keyboard users are not stranded behind it.
    ref.current?.focus();
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 16, 20, 0.55)",
        display: "grid",
        placeItems: "center",
        padding: "var(--s4)",
        zIndex: 50,
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-lg)",
          boxShadow: "var(--shadow-3)",
          width,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--s3)",
            padding: "var(--s3) var(--s4)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <h3>{title}</h3>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close dialog">
            ✕
          </Button>
        </div>
        <div style={{ padding: "var(--s4)", overflowY: "auto", flex: 1 }}>{children}</div>
        {footer && (
          <div
            style={{
              padding: "var(--s3) var(--s4)",
              borderTop: "1px solid var(--line)",
              background: "var(--surface-2)",
              display: "flex",
              gap: "var(--s2)",
              justifyContent: "flex-end",
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Toast ──────────────────────────────────────────────────────────────── */

type Toast = { id: number; message: string; tone: "ok" | "danger" | "info" };
const ToastContext = React.createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function useToast() {
  return React.useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const push = React.useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        style={{
          position: "fixed",
          bottom: "var(--s4)",
          right: "var(--s4)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--s2)",
          zIndex: 60,
          maxWidth: "min(30rem, 90vw)",
        }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            style={{
              background: "var(--surface)",
              border: `1px solid var(--${t.tone === "info" ? "line" : t.tone})`,
              borderLeft: `3px solid var(--${t.tone === "info" ? "accent" : t.tone})`,
              borderRadius: "var(--radius)",
              boxShadow: "var(--shadow-2)",
              padding: "var(--s3) var(--s4)",
              fontSize: "var(--text-sm)",
            }}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}


/**
 * Copy generated content so it can be checked in another model.
 *
 * `navigator.clipboard` needs a secure context and is not available over plain
 * http on a LAN address, which is exactly how this console is served — so fall
 * back to a hidden textarea rather than failing silently.
 */
export function CopyButton({
  label = "Copy",
  getText,
  size = "sm",
  variant = "ghost",
  title,
}: {
  label?: string;
  getText: () => string;
  size?: "sm" | "md";
  variant?: "primary" | "secondary" | "ghost" | "danger";
  title?: string;
}) {
  const [state, setState] = React.useState<"idle" | "done" | "failed">("idle");

  async function copy() {
    const text = getText();
    if (!text.trim()) {
      setState("failed");
      window.setTimeout(() => setState("idle"), 1600);
      return;
    }
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      setState("done");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 1600);
  }

  return (
    <Button
      size={size}
      variant={variant}
      onClick={copy}
      title={title || "Copy as text for checking in another model"}
    >
      {state === "done" ? "Copied" : state === "failed" ? "Nothing to copy" : label}
    </Button>
  );
}
