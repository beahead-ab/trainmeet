import "@trainmeet/design/design.css";
import "./lokforaren.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Lok } from "./store";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App lok={new Lok()} />
    </StrictMode>,
  );
}

// The app's shell in the phone, so that it opens at the meet without the network (LOK-14). Only
// the shell: never the API (public/sw.js).
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/lokforaren/sw.js", { scope: "/lokforaren/" }).catch(() => undefined);
  });
}
