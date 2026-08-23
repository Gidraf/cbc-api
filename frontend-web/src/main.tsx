import React, { Component, ErrorInfo, ReactNode } from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught React Error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "2rem", maxWidth: "600px", margin: "2rem auto", background: "#fef2f2", border: "1px solid #f87171", borderRadius: "8px" }}>
          <h2 style={{ color: "#991b1b", marginTop: 0 }}>An unexpected UI error occurred</h2>
          <p style={{ color: "#7f1d1d", fontSize: "0.9rem" }}>{this.state.error?.message}</p>
          <button
            onClick={() => {
              this.setState({ hasError: false, error: null });
              window.location.reload();
            }}
            style={{ marginTop: "1rem", padding: "8px 16px", background: "#dc2626", color: "#ffffff", border: "none", borderRadius: "4px", cursor: "pointer" }}
          >
            Reload Application
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
