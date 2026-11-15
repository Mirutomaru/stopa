import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { CaseSummary } from "./api";

/** Globální výběr případu (dashboard → podstránky). Instance mezi komponentami
 *  synchronizují přes DOM event `stopa:case-changed` + localStorage. */
export function useCurrentCase() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [currentId, setCurrentId] = useState<string>(() => localStorage.getItem("stopa.case") ?? "");
  const [error, setError] = useState<string | null>(null);

  const reloadCases = useCallback(() => {
    api.listCases()
      .then(setCases)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    reloadCases();
    // synchronizace s ostatními instancemi (výběr v jiné komponentě / LiveBadge)
    const onCaseChanged = () => setCurrentId(localStorage.getItem("stopa.case") ?? "");
    window.addEventListener("stopa:case-changed", onCaseChanged);
    return () => window.removeEventListener("stopa:case-changed", onCaseChanged);
  }, [reloadCases]);

  const select = useCallback((id: string) => {
    localStorage.setItem("stopa.case", id);
    setCurrentId(id);
    window.dispatchEvent(new Event("stopa:case-changed"));
  }, []);

  const current = cases.find((c) => c.id === currentId) ?? null;
  return { cases, error, current, currentId, select, reloadCases };
}

export function useFetch<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn().then(
      (d) => { if (alive) { setData(d); setLoading(false); } },
      (e: unknown) => { if (alive) { setError(e instanceof ApiError ? e.message : String(e)); setLoading(false); } },
    );
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  const reload = useCallback(() => {
    fn().then(
      (d) => { setData(d); setError(null); setLoading(false); },
      (e: unknown) => { setError(e instanceof ApiError ? e.message : String(e)); setLoading(false); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, loading, error, reload };
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}
