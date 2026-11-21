import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { I18nProvider } from "./i18n";
import { live } from "./lib/live";
import "./styles.css";

// F4.2 — clean WS teardown při opouštění stránky (graceful degradation).
window.addEventListener("pagehide", () => live.disconnect());

// P4-4 W3 — SPA je kanonická na root URL; /spa/ zůstává alias (staré odkazy/bookmarky).
const base = window.location.pathname.startsWith("/spa") ? "/spa" : "";

// F4.1 — offline-first (AK): Service Worker cache-first pro statické assety.
// P4-4 W3 — explicitní scope "/" → offline-first funguje i při servírování z root URL
// (script /spa/sw.js je dostupný z obou kořenů; .catch = fail-soft jako v F4.1).
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/spa/sw.js", { scope: "/" }).catch(() => undefined);
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={base}>
      <I18nProvider>
        <App />
      </I18nProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
