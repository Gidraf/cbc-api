import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./app/AppShell";
import { RouteBoundary } from "./app/RouteBoundary";
import { AuthProvider, useAuth } from "./lib/auth";
import { LoadingBlock, ToastProvider } from "./ui/components";

import { Approvals } from "./views/Approvals";
import { Coverage } from "./views/Coverage";
import { ContentFactory } from "./views/ContentFactory";
import { Datasets } from "./views/Datasets";
import { Profiles } from "./views/Profiles";
import { StageModels } from "./views/StageModels";
import { DiagramLibrary } from "./views/DiagramLibrary";
import { ExamBuilder } from "./views/ExamBuilder";
import { MediaLibrary } from "./views/MediaLibrary";
import { Overview } from "./views/Overview";
import { Pipelines } from "./views/Pipelines";
import { QuestionBank } from "./views/QuestionBank";
import { Review } from "./views/Review";
import { SignIn } from "./views/SignIn";

import "./ui/tokens.css";

// The legacy console is ~9,600 lines and its own stylesheet. Loading it lazily
// keeps it out of the initial bundle for the screens that replaced it.
const Legacy = React.lazy(() => import("./views/Legacy").then((m) => ({ default: m.Legacy })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Generation is slow and expensive; refetching on every window focus
      // would re-run reports the operator is still reading.
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        const status = (error as any)?.status;
        // Never retry an auth or validation failure — it will fail identically.
        if (status === 401 || status === 403 || (status >= 400 && status < 500)) return false;
        return failureCount < 2;
      },
      staleTime: 20_000,
    },
  },
});

/** Each route gets its own boundary so one broken screen cannot blank the console. */
function Screen({ name, children }: { name: string; children: React.ReactNode }) {
  // Suspense here as well as at the boundary: a lazy child suspending during a
  // navigation is a normal thing to do, and without a boundary above it React
  // treats it as an error and blanks the screen.
  return (
    <RouteBoundary name={name}>
      <React.Suspense fallback={<LoadingBlock rows={5} label={`Loading ${name}`} />}>
        {children}
      </React.Suspense>
    </RouteBoundary>
  );
}

function Router() {
  const { token } = useAuth();

  if (!token) return <SignIn />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Screen name="Overview"><Overview /></Screen>} />
        <Route path="pipelines" element={<Screen name="Pipelines"><Pipelines /></Screen>} />
        <Route path="coverage" element={<Screen name="Curriculum coverage"><Coverage /></Screen>} />
        <Route path="factory" element={<Screen name="Content factory"><ContentFactory /></Screen>} />
        <Route path="questions" element={<Screen name="Question bank"><QuestionBank /></Screen>} />
        <Route path="exams" element={<Screen name="Exam builder"><ExamBuilder /></Screen>} />
        <Route path="diagrams" element={<Screen name="Diagram library"><DiagramLibrary /></Screen>} />
        <Route path="media" element={<Screen name="Photo and video library"><MediaLibrary /></Screen>} />
        <Route path="review" element={<Screen name="Review queue"><Review /></Screen>} />
        <Route
          path="approvals"
          element={<Screen name="Versions and approval"><Approvals /></Screen>}
        />
        <Route path="datasets" element={<Screen name="Datasets"><Datasets /></Screen>} />
        <Route path="skills" element={<Screen name="Teaching skills"><Profiles /></Screen>} />
        <Route path="models" element={<Screen name="Model per station"><StageModels /></Screen>} />
        <Route
          path="legacy"
          element={
            <Screen name="Advanced console">
              <React.Suspense fallback={<LoadingBlock rows={6} label="Loading the advanced console" />}>
                <Legacy />
              </React.Suspense>
            </Screen>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <RouteBoundary name="Application">
              <Router />
            </RouteBoundary>
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
