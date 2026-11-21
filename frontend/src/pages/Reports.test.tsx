import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ReportsPage from "./Reports";
import { I18nProvider } from "../i18n";

const listCases = vi.fn();
vi.mock("../lib/api", () => ({
  api: {
    listCases: (...a: unknown[]) => listCases(...a),
    daubertPackUrl: (id: string) => `/api/cases/${id}/daubert-pack`,
  },
  ApiError: class extends Error {},
}));

const CASE = {
  id: "case-rep", name: "Případ REP", examiner: null, created_at: "2026-11-20T10:00:00",
  files: 2, bytes: 4096, bad_ext: 0, dups: 0, artifacts: 1,
  auto_export_enabled: false, auto_export_interval_minutes: null,
};

function renderPage() {
  localStorage.setItem("stopa.case", CASE.id);
  return render(
    <MemoryRouter>
      <I18nProvider>
        <ReportsPage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("Reports (P4-4 W2 SPA view, parita F5.5 Daubert)", () => {
  beforeEach(() => {
    localStorage.clear();
    listCases.mockReset().mockResolvedValue([CASE]);
  });

  it("Daubert pack tlačítko otevře JSON pro soud (parita s legacy window.open)", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Případ REP");
    });
    // popisek sekce + popis balíku (F5.5)
    expect(screen.getByText(/Daubert challenge preparedness pack/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /Daubert pack \(JSON\)/ });
    fireEvent.click(btn);
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/api/cases/case-rep/daubert-pack");
    openSpy.mockRestore();
  });

  it("bez vybraného případu → odkaz na Případy", async () => {
    listCases.mockResolvedValue([]);
    render(
      <MemoryRouter>
        <I18nProvider>
          <ReportsPage />
        </I18nProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/← Případy/)).toBeInTheDocument());
  });
});
