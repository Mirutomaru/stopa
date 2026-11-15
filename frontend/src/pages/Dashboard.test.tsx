import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DashboardPage from "./Dashboard";
import { I18nProvider } from "../i18n";

const listCases = vi.fn();
vi.mock("../lib/api", () => ({
  api: {
    listCases: (...a: unknown[]) => listCases(...a),
    createCase: vi.fn().mockResolvedValue({ id: "case-new" }),
  },
  ApiError: class extends Error {},
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <DashboardPage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("Dashboard (smoke)", () => {
  beforeEach(() => {
    localStorage.clear();
    listCases.mockReset();
  });

  it("vykreslí seznam případů z API", async () => {
    listCases.mockResolvedValue([
      { id: "case-a", name: "Případ Alfa", examiner: "Matúš", created_at: "2026-11-15T10:00:00", files: 42, bytes: 1024, bad_ext: 0, dups: 1, artifacts: 7, auto_export_enabled: false, auto_export_interval_minutes: null },
    ]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Případ Alfa")).toBeInTheDocument());
    expect(listCases).toHaveBeenCalledTimes(1);
  });

  it("chybné API → viditelná chyba", async () => {
    listCases.mockRejectedValue(new Error("sraz"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/Chyba:/)).toBeInTheDocument());
  });
});
