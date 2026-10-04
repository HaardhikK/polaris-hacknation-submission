import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import "./researchers.css";
import { ErrorBoundary } from "../shared/Layout";
import ResearcherApp from "./ResearcherApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary tag="researcher view">
      <ResearcherApp />
    </ErrorBoundary>
  </StrictMode>,
);
