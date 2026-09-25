import React from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Badge, Button } from "../ui/components";

type NavItem = { to: string; label: string; icon: string; right?: string; hint: string };

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Produce",
    items: [
      { to: "/", label: "Overview", icon: "◇", right: "read", hint: "Where the factory stands today" },
      {
        to: "/pipelines",
        label: "Pipelines",
        icon: "⛓",
        right: "read",
        hint: "Every grade as a project, stage by stage — what is built, what passed, what is stuck",
      },
      { to: "/coverage", label: "Curriculum coverage", icon: "▤", right: "read", hint: "What is done and what is left, per grade" },
      {
        to: "/design-coverage",
        label: "KICD design coverage",
        icon: "◫",
        right: "read",
        hint: "Which outcomes, inquiry questions and competencies have a question against them",
      },
      { to: "/factory", label: "Content factory", icon: "⚒", right: "generate", hint: "Notes, diagrams, activities, questions" },
    ],
  },
  {
    group: "Assess",
    items: [
      { to: "/studio", label: "Exam studio", icon: "✎", right: "build", hint: "Build a paper step by step and see it as it prints" },
      { to: "/questions", label: "Question bank", icon: "?", right: "read", hint: "Every approved item, in curriculum order" },
      { to: "/exams", label: "Exam builder", icon: "▦", right: "read", hint: "Compose and print papers" },
      { to: "/diagrams", label: "Diagram library", icon: "◈", right: "read", hint: "Reusable visuals and their parts" },
      {
        to: "/media",
        label: "Photos & videos",
        icon: "▨",
        hint: "Every planned image and video, shown as pictures",
      },
    ],
  },
  {
    group: "Operate",
    items: [
      // "generate" is admin + operator, matching who the sync/process endpoints
      // actually accept. There is no "datasets" right, so naming one would have
      // hidden this screen from every role.
      { to: "/queue", label: "Queue", icon: "≡", right: "generate", hint: "Every job live: running, waiting, done, failed — and why" },
      { to: "/datasets", label: "Datasets", icon: "▤", right: "generate", hint: "Curriculum designs waiting to be ingested" },
      { to: "/skills", label: "Teaching skills", icon: "◎", right: "generate", hint: "Per-subject expertise injected into every prompt" },
      { to: "/models", label: "Model per station", icon: "⚙", right: "generate", hint: "Which model runs the notes, the diagrams, the ingest — and what each costs you" },
      // "configure" is admin only: approving a switch changes the model behind
      // every guide and question on the platform.
      { to: "/scout", label: "Model scout", icon: "◎", right: "configure", hint: "Weekly prices and trials of cheaper models — approve or roll back a switch" },
      { to: "/agents", label: "Agent tasks", icon: "⟳", right: "generate", hint: "What Antigravity, Claude Code, Codex or Ollama are doing here right now, and what they did" },
      { to: "/keys", label: "API keys", icon: "🔑", right: "generate", hint: "Add or rotate a provider key without rebuilding anything" },
      { to: "/settings", label: "Settings", icon: "⚙", right: "generate", hint: "Public address, the name on papers, log retention, webhooks" },
      {
        to: "/prompts",
        label: "Domain prompts",
        icon: "❏",
        right: "generate",
        hint: "Maps, equations, sol-fa, cutting lists — one small prompt each, improved on its own",
      },
      { to: "/review", label: "Review queue", icon: "✓", right: "review", hint: "Bundles awaiting a human decision" },
      {
        to: "/approvals",
        label: "Versions & approval",
        icon: "⌥",
        right: "review",
        hint: "Every version, its layered review scores, and the approved label",
      },
    ],
  },
];

export function AppShell() {
  const { username, role, signOut, can } = useAuth();
  const location = useLocation();
  const [navOpen, setNavOpen] = React.useState(false);

  // Close the mobile drawer on navigation, otherwise it covers the new page.
  React.useEffect(() => setNavOpen(false), [location.pathname]);

  const theme = useThemeToggle();

  return (
    <div style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <header
        style={{
          height: "var(--header-h)",
          display: "flex",
          alignItems: "center",
          gap: "var(--s3)",
          padding: "0 var(--s4)",
          background: "var(--surface)",
          borderBottom: "1px solid var(--line)",
          position: "sticky",
          top: 0,
          zIndex: 30,
        }}
      >
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setNavOpen((v) => !v)}
          aria-expanded={navOpen}
          aria-controls="main-nav"
          style={{ display: "none" }}
          className="nav-toggle"
        >
          ☰
        </Button>

        <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", minWidth: 0 }}>
          <strong style={{ fontSize: "var(--text-lg)", letterSpacing: "-0.02em" }}>CBC Factory</strong>
          <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>Content production console</span>
        </div>

        <div style={{ flex: 1 }} />

        <Button variant="ghost" size="sm" onClick={theme.toggle} aria-label={`Switch to ${theme.next} theme`}>
          {theme.current === "dark" ? "☀" : "☾"}
        </Button>

        <div style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{username}</span>
          {role && <Badge tone="accent">{role}</Badge>}
        </div>

        <Button size="sm" onClick={signOut}>
          Sign out
        </Button>
      </header>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <nav
          id="main-nav"
          aria-label="Primary"
          data-open={navOpen}
          className="app-nav"
          style={{
            width: "var(--nav-w)",
            flexShrink: 0,
            background: "var(--surface)",
            borderRight: "1px solid var(--line)",
            padding: "var(--s4) var(--s3)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--s5)",
            overflowY: "auto",
          }}
        >
          {NAV.map((section) => {
            const visible = section.items.filter((i) => !i.right || can(i.right));
            if (!visible.length) return null;
            return (
              <div key={section.group} style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
                <span
                  style={{
                    fontSize: "var(--text-xs)",
                    fontWeight: 650,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "var(--ink-3)",
                    padding: "0 var(--s2)",
                  }}
                >
                  {section.group}
                </span>
                {visible.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    title={item.hint}
                    style={({ isActive }) => ({
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--s3)",
                      padding: "7px var(--s3)",
                      borderRadius: "var(--radius-sm)",
                      textDecoration: "none",
                      fontSize: "var(--text-sm)",
                      fontWeight: isActive ? 600 : 500,
                      color: isActive ? "var(--accent)" : "var(--ink-2)",
                      background: isActive ? "var(--accent-wash)" : "transparent",
                    })}
                  >
                    <span aria-hidden="true" style={{ width: "1rem", textAlign: "center", opacity: 0.8 }}>
                      {item.icon}
                    </span>
                    {item.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <main
          id="main"
          tabIndex={-1}
          style={{
            flex: 1,
            minWidth: 0,
            padding: "var(--s5)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--s5)",
          }}
        >
          <Outlet />
        </main>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .nav-toggle { display: inline-flex !important; }
          .app-nav {
            position: fixed;
            top: var(--header-h);
            bottom: 0;
            left: 0;
            z-index: 25;
            transform: translateX(-100%);
            transition: transform 0.18s ease;
            box-shadow: var(--shadow-2);
          }
          .app-nav[data-open="true"] { transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}

function useThemeToggle() {
  const [current, setCurrent] = React.useState<"light" | "dark">(() => {
    const stored = localStorage.getItem("cbc_theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", current);
    localStorage.setItem("cbc_theme", current);
  }, [current]);

  return {
    current,
    next: current === "dark" ? "light" : "dark",
    toggle: () => setCurrent((c) => (c === "dark" ? "light" : "dark")),
  };
}
