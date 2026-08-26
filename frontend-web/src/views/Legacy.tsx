import React from "react";
import { App as LegacyConsole } from "../App";
import { Card, PageHeader } from "../ui/components";
import "../styles.css";

/**
 * The original single-file console, mounted as one route.
 *
 * The rebuilt screens cover the production and assessment workflows. Prompt
 * editing, provider configuration, pipeline bindings, subject profiles and the
 * browser agent still live here and are reachable rather than lost. They share
 * the same auth token, so no second sign-in is needed.
 */
export function Legacy() {
  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Advanced console"
        description="Prompt registry, model providers, pipeline stage bindings, subject profiles, dataset ingestion and the browser agent. These screens have not been rebuilt yet and are shown here unchanged."
      />
      <Card padded={false} accent="info">
        <div style={{ isolation: "isolate" }}>
          <LegacyConsole />
        </div>
      </Card>
    </>
  );
}
