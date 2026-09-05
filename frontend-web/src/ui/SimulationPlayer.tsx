import React from "react";
import { MathBlock } from "./MathBlock";
import { canSpeak, pauseSpeech, resumeSpeech, speak, stopSpeech, type SpeakHandle } from "../lib/speech";

export interface SimulationStep {
  index: number;
  duration_ms: number;
  latex: string;
  plain: string;
  narration: string;
  audio_url?: string | null;
  // "recorded" when a person read it aloud, otherwise the synthesiser.
  audio_source?: string;
  svg_highlight?: string;
  animation_type?: string;
}

export interface SimulationTrack {
  simulation_id: string;
  curriculum_link?: any;
  title: string;
  total_duration_ms: number;
  source_type?: string;
  steps: SimulationStep[];
  created_at?: string;
}

export interface SimulationPlayerProps {
  track: SimulationTrack | null;
  compact?: boolean;
  onClose?: () => void;
}

export function SimulationPlayer({ track, compact = false, onClose }: SimulationPlayerProps) {
  const [currentStepIdx, setCurrentStepIdx] = React.useState(0);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const timerRef = React.useRef<any>(null);
  const speechRef = React.useRef<SpeakHandle | null>(null);
  // Which of the three tiers is actually carrying this step, so the player can
  // say so rather than leaving a silent step looking broken.
  const [voicing, setVoicing] = React.useState<"file" | "device" | "silent">("silent");

  const steps = track?.steps || [];
  const currentStep = steps[currentStepIdx] || null;
  const totalSteps = steps.length;

  // Cleanup audio & timer on unmount or track change
  React.useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      // A walkthrough closed mid-sentence must not keep talking over whatever
      // the operator opens next.
      speechRef.current?.cancel();
      speechRef.current = null;
      stopSpeech();
    };
  }, [track]);

  const advanceStep = React.useCallback(() => {
    setCurrentStepIdx((prev) => {
      if (prev + 1 < totalSteps) {
        return prev + 1;
      }
      setIsPlaying(false);
      return prev;
    });
  }, [totalSteps]);

  // Handle play/pause and audio synchronization
  React.useEffect(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    speechRef.current?.cancel();
    speechRef.current = null;

    if (!isPlaying || !currentStep) return;

    const onTimer = () => {
      setVoicing("silent");
      timerRef.current = setTimeout(advanceStep, currentStep.duration_ms || 4000);
    };

    // Three tiers, best first.
    //
    //   a synthesised file  — the voice somebody chose and paid for
    //   this device's voice — free, instant, offline, and it needs no storage
    //   a timer             — silence, advancing on an estimate of the words
    //
    // The middle one is where nearly every walkthrough sits: narration costs a
    // call per step to synthesise, so most steps have no file and used to be
    // read in silence. Every tier ends the same way — when the words finish,
    // the step advances — so the timing follows the narration rather than
    // guessing at its length.
    if (currentStep.audio_url) {
      const audio = new Audio(currentStep.audio_url);
      audioRef.current = audio;
      setVoicing("file");
      audio.onended = advanceStep;
      audio.onerror = () => speakStep();
      audio.play().catch(() => {
        // Autoplay refused, or the file is gone. The device can still read it.
        speakStep();
      });
      return;
    }

    speakStep();

    function speakStep() {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      const words = (currentStep?.narration || "").trim();
      if (!canSpeak() || !words) {
        onTimer();
        return;
      }
      setVoicing("device");
      speechRef.current = speak(words, {
        onEnd: advanceStep,
        onError: () => onTimer(),
      });
    }
  }, [isPlaying, currentStepIdx, currentStep, advanceStep]);

  if (!track || steps.length === 0) {
    return (
      <div style={{ padding: "16px", textAlign: "center", color: "#6b7280", fontStyle: "italic" }}>
        No walkthrough steps available.
      </div>
    );
  }

  const togglePlay = () => {
    if (currentStepIdx >= totalSteps - 1 && !isPlaying) {
      setCurrentStepIdx(0);
    }
    // Pause has to stop the speaking too, or the narration carries on over a
    // paused walkthrough and finishes by advancing it.
    if (isPlaying) pauseSpeech();
    else resumeSpeech();
    setIsPlaying(!isPlaying);
  };

  const handlePrev = () => {
    if (currentStepIdx > 0) {
      setCurrentStepIdx(currentStepIdx - 1);
    }
  };

  const handleNext = () => {
    if (currentStepIdx < totalSteps - 1) {
      setCurrentStepIdx(currentStepIdx + 1);
    }
  };

  const handleReplay = () => {
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
      audioRef.current.play().catch(() => {});
    } else {
      // re-trigger step
      setCurrentStepIdx((i) => i);
    }
  };

  const progressPct = totalSteps > 0 ? ((currentStepIdx + 1) / totalSteps) * 100 : 0;

  return (
    <div
      style={{
        background: "#ffffff",
        border: "1.5px solid #0B6E5F",
        borderRadius: "8px",
        boxShadow: "0 4px 12px rgba(11, 110, 95, 0.08)",
        overflow: "hidden",
        margin: compact ? "8px 0" : "14px 0",
      }}
    >
      {/* Header */}
      <div
        style={{
          background: "#064E3B",
          color: "#ffffff",
          padding: "8px 14px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", fontWeight: 600 }}>
          <span>📐 Worked walkthrough</span>
          <span style={{ opacity: 0.8, fontSize: "11px", fontWeight: 400 }}>
            {track.title || "Step-by-Step Solution"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              background: "rgba(255,255,255,0.2)",
              padding: "2px 8px",
              borderRadius: "12px",
              fontSize: "11px",
            }}
          >
            Step {currentStepIdx + 1} of {totalSteps}
          </span>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                background: "transparent",
                border: "none",
                color: "#ffffff",
                cursor: "pointer",
                fontSize: "14px",
                lineHeight: 1,
              }}
              title="Close walkthrough"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div style={{ width: "100%", height: "4px", background: "#e5e7eb" }}>
        <div
          style={{
            width: `${progressPct}%`,
            height: "100%",
            background: "#0B6E5F",
            transition: "width 0.3s ease",
          }}
        />
      </div>

      {/* Active Step Canvas */}
      <div
        style={{
          padding: compact ? "14px" : "20px",
          textAlign: "center",
          background: "#f9fafb",
          minHeight: compact ? "80px" : "110px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        {currentStep ? (
          <div style={{ maxWidth: "100%", overflowX: "auto" }}>
            <MathBlock latex={currentStep.latex} display style={{ fontSize: compact ? "16px" : "20px" }} />
          </div>
        ) : (
          <div style={{ color: "#6b7280" }}>Select a step to begin</div>
        )}
      </div>

      {/* Spoken Narration Box */}
      {currentStep && (
        <div
          style={{
            padding: "10px 14px",
            background: "#f0fdf4",
            borderTop: "1px solid #dcfce7",
            borderBottom: "1px solid #dcfce7",
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
            fontSize: "13px",
            color: "#166534",
            lineHeight: 1.5,
          }}
        >
          <span
            style={{ fontSize: "16px", marginTop: "1px" }}
            title={
              voicing === "file" && currentStep.audio_source === "recorded"
                ? "A teacher's own recording"
                : voicing === "file"
                ? "Narrated by a speech synthesiser"
                : voicing === "device"
                ? "Read aloud by this device — no recording needed"
                : "No voice on this device; the step advances on its own timing"
            }
          >
            {voicing === "file"
              ? currentStep.audio_source === "recorded"
                ? "🎙"
                : "🔊"
              : voicing === "device"
              ? "🗣"
              : "💬"}
          </span>
          <div style={{ flex: 1 }}>
            <strong>Teacher Explanation:</strong> {currentStep.narration}
          </div>
        </div>
      )}

      {/* Control Bar */}
      <div
        style={{
          padding: "8px 14px",
          background: "#ffffff",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", gap: "6px" }}>
          <button
            onClick={handlePrev}
            disabled={currentStepIdx === 0}
            style={{
              padding: "4px 10px",
              borderRadius: "4px",
              border: "1px solid #d1d5db",
              background: currentStepIdx === 0 ? "#f3f4f6" : "#ffffff",
              color: currentStepIdx === 0 ? "#9ca3af" : "#374151",
              cursor: currentStepIdx === 0 ? "not-allowed" : "pointer",
              fontSize: "12px",
            }}
          >
            ◀ Prev
          </button>
          <button
            onClick={togglePlay}
            style={{
              padding: "4px 14px",
              borderRadius: "4px",
              border: "none",
              background: "#0B6E5F",
              color: "#ffffff",
              cursor: "pointer",
              fontSize: "12px",
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            {isPlaying ? "⏸ Pause" : "▶ Play"}
          </button>
          <button
            onClick={handleNext}
            disabled={currentStepIdx >= totalSteps - 1}
            style={{
              padding: "4px 10px",
              borderRadius: "4px",
              border: "1px solid #d1d5db",
              background: currentStepIdx >= totalSteps - 1 ? "#f3f4f6" : "#ffffff",
              color: currentStepIdx >= totalSteps - 1 ? "#9ca3af" : "#374151",
              cursor: currentStepIdx >= totalSteps - 1 ? "not-allowed" : "pointer",
              fontSize: "12px",
            }}
          >
            Next ▶
          </button>
          <button
            onClick={handleReplay}
            title="Replay Current Step"
            style={{
              padding: "4px 8px",
              borderRadius: "4px",
              border: "1px solid #d1d5db",
              background: "#ffffff",
              color: "#374151",
              cursor: "pointer",
              fontSize: "12px",
            }}
          >
            🔁
          </button>
        </div>

        {/* Step Selector dots */}
        <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
          {steps.map((s, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentStepIdx(idx)}
              style={{
                width: "18px",
                height: "18px",
                borderRadius: "50%",
                border: "none",
                background: currentStepIdx === idx ? "#0B6E5F" : "#e5e7eb",
                color: currentStepIdx === idx ? "#ffffff" : "#6b7280",
                fontSize: "10px",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: currentStepIdx === idx ? 700 : 400,
              }}
              title={`Step ${idx + 1}: ${s.latex}`}
            >
              {idx + 1}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
