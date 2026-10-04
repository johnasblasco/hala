import type { AuditResult, Job, Lead, Settings, Stats } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  stats: () => request<Stats>("/api/stats"),
  search: (queries: string[], source: string) =>
    request<Job>("/api/search", { method: "POST", body: json({ queries, source }) }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  leads: (params: { kind?: string; status?: string; q?: string }) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][],
    );
    return request<Lead[]>(`/api/leads?${qs}`);
  },
  lead: (id: number) => request<Lead>(`/api/leads/${id}`),
  updateLead: (id: number, changes: Partial<Lead>) =>
    request<Lead>(`/api/leads/${id}`, { method: "PATCH", body: json(changes) }),
  deleteLead: (id: number) => request<{ ok: boolean }>(`/api/leads/${id}`, { method: "DELETE" }),
  refreshLead: (id: number) => request<Lead>(`/api/leads/${id}/refresh`, { method: "POST" }),
  audit: (url: string) => request<AuditResult>("/api/audit", { method: "POST", body: json({ url }) }),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (values: Record<string, string>) =>
    request<Settings>("/api/settings", { method: "PUT", body: json(values) }),
  clearSecret: (key: string) => request<Settings>(`/api/settings/${key}`, { method: "DELETE" }),
};
