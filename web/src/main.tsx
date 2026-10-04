import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { ErrorBoundary } from "./shared/Layout";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary tag="family view">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
