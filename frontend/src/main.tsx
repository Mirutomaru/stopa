import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n";
import { live } from "./lib/live";
import "./styles.css";

// F4.2 — clean WS teardown při opouštění stránky (graceful degradation).
window.addEventListener("pagehide", () => live.disconnect());

// F4.1 — offline-first (AK): Service Worker cache-first pro statické assety.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/spa/sw.js").catch(() => undefined);
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/spa">
      <I18nProvider>
        <App />
      </I18nProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
