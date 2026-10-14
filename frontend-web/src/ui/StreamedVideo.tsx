import React from "react";
import { useWatchLink } from "../lib/queries";
import { useToast } from "./components";

/** Streams a video in the page: a short-lived link, no download, no picture-in-picture. */
export function StreamedVideo({ questionId }: { questionId: string }) {
  const link = useWatchLink();
  const toast = useToast();
  const [src, setSrc] = React.useState("");
  React.useEffect(() => {
    let alive = true;
    link.mutateAsync(questionId).then((out) => { if (alive) setSrc(out.stream_url); })
      .catch((err) => toast(err instanceof Error ? err.message : "Could not open the video.", "danger"));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId]);
  if (!src) return <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>Opening the video…</span>;
  return (
    <video src={src} controls autoPlay controlsList="nodownload noplaybackrate" disablePictureInPicture disableRemotePlayback
           onContextMenu={(e) => e.preventDefault()}
           style={{ flexBasis: "100%", width: "100%", borderRadius: "var(--radius)", background: "#000" }} />
  );
}

