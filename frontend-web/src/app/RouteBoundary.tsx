import React from "react";
import { Button, Card } from "../ui/components";

/**
 * Per-route error boundary.
 *
 * The console had a single boundary at the root, so one malformed API response
 * anywhere blanked the entire application. Wrapping each route means a broken
 * screen stays broken on its own while the rest of the console keeps working.
 */
export class RouteBoundary extends React.Component<
  { children: React.ReactNode; name: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`Error in ${this.props.name}:`, error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <Card title={`${this.props.name} could not render`} accent="danger">
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)", alignItems: "flex-start" }}>
          <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", maxWidth: "60ch" }}>
            This screen hit an error. The rest of the console is unaffected — you can navigate away, or
            try rendering it again.
          </p>
          <pre
            style={{
              background: "var(--surface-2)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
              fontSize: "var(--text-xs)",
              overflowX: "auto",
              maxWidth: "100%",
              margin: 0,
            }}
          >
            {this.state.error.message}
          </pre>
          <Button variant="primary" size="sm" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
        </div>
      </Card>
    );
  }
}
