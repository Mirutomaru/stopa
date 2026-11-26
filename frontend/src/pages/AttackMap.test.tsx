import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AttackMapPage from "./AttackMap";
import { I18nProvider } from "../i18n";

const listCases = vi.fn();
const attackMap = vi.fn();
vi.mock("../lib/api", () => ({
  api: {
    listCases: (...a: unknown[]) => listCases(...a),
    attackMap: (...a: unknown[]) => attackMap(...a),
    attackMapStixUrl: (id: string) => `/api/cases/${id}/attack-map?format=stix`,
  },
  ApiError: class extends Error {},
}));

const CASE = {
  id: "case-atk", name: "Případ ATK", examiner: null, created_at: "2026-11-20T10:00:00",
  files: 4, bytes: 8192, bad_ext: 0, dups: 0, artifacts: 5,
  auto_export_enabled: false, auto_export_interval_minutes: null,
};

const HEATMAP = {
  tactics: [
    { id: "TA0001", name: "Initial Access" },
    { id: "TA0002", name: "Execution" },
    { id: "TA0040", name: "Impact" }, // bez hitů — má se nevykreslit (parita F6.3)
  ],
  techniques: [
    { id: "T1567", name: "Web Shell Upload", tactic: "TA0002", count: 3 },
    { id: "T1204", name: "User Execution", tactic: "TA0002", count: 1 },
    { id: "T1195", name: "Spearphishing Attachment", tactic: "TA0001", count: 2 },
  ],
  cells: {
    T1567: [
      { artifact_type: "file_hash", title: "shell.php (md5 a1b2)", rel_path: "evidence/shell.php" },
      { artifact_type: "network_connection", title: "POST /upload", rel_path: null },
    ],
    T1204: [{ artifact_type: "file_hash", title: null, rel_path: "evidence/doc.exe" }],
  },
  summary: {
    artifacts_total: 5, mapped_artifacts: 4, unmapped_artifacts: 1,
    techniques_hit: 3, tactics_hit: 2, coverage_pct: 80.0,
  },
};

function renderPage() {
  localStorage.setItem("stopa.case", CASE.id);
  return render(
    <MemoryRouter>
      <I18nProvider>
        <AttackMapPage />
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("AttackMap (P4-4 W2 SPA view, parita F6.3)", () => {
  beforeEach(() => {
    localStorage.clear();
    listCases.mockReset().mockResolvedValue([CASE]);
    attackMap.mockReset();
  });

  it("vykreslí summary + heat-mapa jen pro taktiky s hity", async () => {
    attackMap.mockResolvedValue(HEATMAP);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Případ ATK");
    });
    // druhý fetch (attackMap) spouští effect PO commitu s headingem — na pomalejší CI
    // může poll detekovat heading dříve než effect vyvolá volání → spy race, proto waitFor.
    await waitFor(() => {
      expect(attackMap).toHaveBeenCalledTimes(1);
    });
    // summary řádek (parita s legacy F6.3) — data z druhého fetchu mohou dorazit až po
    // headingu (první fetch) → race, proto waitFor; zbytek sekce je ze stejného render
    // pass a následuje synchronně.
    await waitFor(() => {
      expect(screen.getByText(/Artefakty: 5/)).toBeInTheDocument();
    });
    expect(screen.getByText(/mapováno: 4/)).toBeInTheDocument();
    expect(screen.getByText(/bez techniky: 1/)).toBeInTheDocument();
    expect(screen.getByText(/techniky s hity: 3/)).toBeInTheDocument();
    // STIX intrusion-set export (F6.3)
    const stix = screen.getByRole("link", { name: /STIX intrusion-set export/ });
    expect(stix).toHaveAttribute("href", "/api/cases/case-atk/attack-map?format=stix");
    // taktiky s hity se vykreslí; TA0040 (Impact) bez hitů ne (parita F6.3)
    expect(screen.getByText("Initial Access")).toBeInTheDocument();
    expect(screen.getByText("Execution")).toBeInTheDocument();
    expect(screen.queryByText("Impact")).not.toBeInTheDocument();
  });

  it("heat buňky: intenzita barvy ∝ count (vzorec 0.15+0.75*count/max) + tooltip vzorky", async () => {
    attackMap.mockResolvedValue(HEATMAP);
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelectorAll(".attack-cell").length).toBe(3));
    const cells = Array.from(container.querySelectorAll<HTMLElement>(".attack-cell"));
    // DOM pořadí: TA0001 T1195 (count 2) → TA0002 T1204 (1), T1567 (3); max=3
    expect(cells[0]).toHaveStyle({ background: "rgba(239, 68, 68, 0.65)" });
    expect(cells[1]).toHaveStyle({ background: "rgba(239, 68, 68, 0.4)" });
    expect(cells[2]).toHaveStyle({ background: "rgba(239, 68, 68, 0.9)" });
    // tooltip = vzorky artefaktů (title; fallback rel_path) — parita s legacy renderAttackMap
    expect(screen.getByTitle("shell.php (md5 a1b2); POST /upload")).toBeInTheDocument();
    expect(screen.getByTitle("evidence/doc.exe")).toBeInTheDocument();
  });

  it("prázdná heat-mapa → explicitní prázdný stav", async () => {
    attackMap.mockResolvedValue({
      ...HEATMAP, techniques: [], cells: {},
      summary: { ...HEATMAP.summary, techniques_hit: 0, tactics_hit: 0, coverage_pct: 0.0 },
    });
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText(/Žádné mapované artefakty/)).toBeInTheDocument());
    expect(container.querySelectorAll(".attack-cell")).toHaveLength(0);
  });

  it("chyba API → error + retry tlačítko", async () => {
    attackMap.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
    // retry klíč (cs) — viz i18n DICT
    const btn = screen.getByRole("button", { name: "Zkusit znovu" });
    expect(btn).toBeInTheDocument();
  });

  it("bez vybraného případu → odkaz na Případy", async () => {
    listCases.mockResolvedValue([]);
    render(
      <MemoryRouter>
        <I18nProvider>
          <AttackMapPage />
        </I18nProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/← Případy/)).toBeInTheDocument());
  });
});
