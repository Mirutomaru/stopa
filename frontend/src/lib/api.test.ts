import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

function mockFetch(body: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: ok ? "OK" : "ERR",
    json: async () => body,
  });
}

describe("api klient", () => {
  it("listCases vrací pole případů", async () => {
    const cases = [{ id: "case-1", name: "Test", files: 3 }];
    vi.stubGlobal("fetch", mockFetch(cases));
    const res = await api.listCases();
    expect(res[0].id).toBe("case-1");
    const [url, init] = (vi.mocked(fetch) as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(url).toBe("/api/cases");
    expect(init?.method).toBeUndefined();
  });

  it("nesplněný status → ApiError s detail z těla", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({ detail: "AI nedostupná — spusťte LM Studio (localhost:1234)" }, false, 503),
    );
    let caught: unknown;
    try {
      await api.aiStatus();
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
    expect((caught as Error).message).toContain("LM Studio");
  });

  it("files konstruuje query string (limit/offset/family)", async () => {
    vi.stubGlobal("fetch", mockFetch([]));
    await api.files("case-x", { limit: 50, offset: 100, family: "doc" });
    const [url] = (vi.mocked(fetch) as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(url).toContain("/api/cases/case-x/files?");
    expect(url).toContain("limit=50");
    expect(url).toContain("offset=100");
    expect(url).toContain("family=doc");
  });

  it("generateHypotheses pošle use_ai=false fallbackem", async () => {
    vi.stubGlobal("fetch", mockFetch({ nodes: [] }));
    await api.generateHypotheses("case-1", false);
    const [, init] = (vi.mocked(fetch) as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(JSON.parse(init?.body ?? "{}")).toEqual({ use_ai: false });
  });

  it("setHypoStatus POST status na správnou cestu", async () => {
    vi.stubGlobal("fetch", mockFetch({ ok: true }));
    await api.setHypoStatus("case-1", "h2", "confirmed");
    const [url, init] = (vi.mocked(fetch) as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(url).toBe("/api/cases/case-1/hypotheses/h2/status");
    expect(JSON.parse(init?.body ?? "{}")).toEqual({ status: "confirmed" });
  });

  it("hypothesisExportUrl obsahuje format", () => {
    expect(api.hypothesisExportUrl("case-9", "pdf")).toBe(
      "/api/cases/case-9/hypotheses/export?format=pdf",
    );
  });
});
