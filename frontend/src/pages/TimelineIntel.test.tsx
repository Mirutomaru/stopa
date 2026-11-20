import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TimelineIntelPage from "./TimelineIntel";
import { I18nProvider } from "../i18n";

const listCases = vi.fn();
const timelineIntel = vi.fn();
vi.mock("../lib/api", () => ({
  api: {
    listCases: (...a: unknown[]) => listCases(...a),
    timelineIntel: (...a: unknown[]) => timelineIntel(...a),
  },
  ApiError: class extends Error {},
}));

const CASE = {
  id: "case-ti", name: "Případ TI", examiner: null, created_at: "2026-11-20T10:00:00",
  files: 3, bytes: 4096, bad_ext: 0, dups: 0, artifacts: 2,
  auto_export_enabled: false, auto_export_interval_minutes: null,
};

const INTEL = {
  case_id: "case-ti",
  events_analyzed: 12,
  gaps: [{
    start_event_id: "ev-1", end_event_id: "ev-7",
    start_ts: "2026-03-01T08:00:00Z", end_ts: "2026-03-02T09:30:00Z", duration_seconds: 95400,
  }],
  outliers: [{ event_id: "ev-9", ts_utc: "2026-03-05T12:00:00Z", prev_gap_seconds: 86400, next_gap_seconds: 172800 }],
  correlations: [{
    group_id: "xc-a1b2c3d4e5f6a7b8", subject: "user:alice", confidence: "confirmed",
    source_ids: ["src-1", "src-2"], event_ids: ["ev-3", "ev-4"],
  }],
  uncertainty: [{ event_id: "ev-9", reasons: ["derived_time", "low_confidence"], severity: "high" }],
  summary: { gaps: 1, outliers: 1, correlation_groups: 1 },
};

function renderPage() {
  localStorage.setItem("stopa.case", CASE.id);
  return render(
    <MemoryRouter>
      <I18nProvider>
        <TimelineIntelPage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("TimelineIntel (P3-6 SPA view, smoke)", () => {
  beforeEach(() => {
    localStorage.clear();
    listCases.mockReset().mockResolvedValue([CASE]);
    timelineIntel.mockReset();
  });

  it("vykreslí všechny sekce z P2-3 API", async () => {
    timelineIntel.mockResolvedValue(INTEL);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Případ TI");
    });
    expect(timelineIntel).toHaveBeenCalledTimes(1);
    // summary řádek s počty
    expect(screen.getByText(/12 analyzováno událostí/)).toBeInTheDocument();
    // gapy: lidě čitelné trvání 95400 s = 26 h 30 min + eventy mezer
    expect(screen.getByText("26 h 30 min")).toBeInTheDocument();
    expect(screen.getByText("ev-1 / ev-7")).toBeInTheDocument();
    // outliery + nejistota: ev-9 se objeví v obou tabulkách
    expect(screen.getAllByText("ev-9").length).toBeGreaterThanOrEqual(2);
    // korelace: subjekt + confidence pill + zdroje
    expect(screen.getByText("user:alice")).toBeInTheDocument();
    expect(screen.getByText("confirmed")).toBeInTheDocument();
    expect(screen.getByText("src-1, src-2")).toBeInTheDocument();
    // nejistota: důvody seřazené lexikálně (backend) → derived_time; low_confidence
    expect(screen.getByText("derived_time; low_confidence")).toBeInTheDocument();
  });

  it("bez vybraného případu ukáže navigační hint", () => {
    timelineIntel.mockResolvedValue(INTEL);
    render(<MemoryRouter><I18nProvider><TimelineIntelPage /></I18nProvider></MemoryRouter>);
    expect(screen.getByText(/← Případy/)).toBeInTheDocument();
  });

  it("chybu API zobrazí s tlačítkem retry", async () => {
    timelineIntel.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/Chyba:/)).toBeInTheDocument());
    expect(screen.getByText("Zkusit znovu")).toBeInTheDocument();
  });
});
