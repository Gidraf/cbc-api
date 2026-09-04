import React from "react";
import { renderLatex, renderMathInText } from "../lib/katex";

export interface MathBlockProps {
  latex: string;
  display?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

export function MathBlock({ latex, display = false, className = "", style }: MathBlockProps) {
  const html = React.useMemo(() => renderLatex(latex, display), [latex, display]);

  if (display) {
    return (
      <div
        className={`math-block-display ${className}`}
        style={{
          margin: "8px 0",
          overflowX: "auto",
          textAlign: "center",
          ...style,
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return (
    <span
      className={`math-block-inline ${className}`}
      style={style}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export interface MathTextProps {
  text: string;
  className?: string;
  style?: React.CSSProperties;
}

export function MathText({ text, className = "", style }: MathTextProps) {
  const html = React.useMemo(() => renderMathInText(text), [text]);

  return (
    <span
      className={`math-text ${className}`}
      style={style}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
