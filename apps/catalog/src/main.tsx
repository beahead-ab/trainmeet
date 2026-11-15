import "@trainmeet/design/design.css";
import "./catalog.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { readLanguage } from "./i18n";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App initialLanguage={readLanguage()} />
    </StrictMode>,
  );
}
