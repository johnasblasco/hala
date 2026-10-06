import { accessToken } from "./auth";
import type { AuditResult, Job, Lead, Settings, Stats } from "./types";

/** Fired when the server says the session is missing or expired. */
export const AUTH_EXPIRED = "hala:auth-expired";

async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = await accessToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED));
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(path, init);
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
  search: (queries: string[], source: string, country: string) =>
    request<Job>("/api/search", { method: "POST", body: json({ queries, source, country }) }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  stepJob: (id: string) => request<Job>(`/api/jobs/${id}/step`, { method: "POST" }),
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
  makePreview: (
    id: number,
    body: { notes: string; photos: string[]; facebook_url: string; language: string },
  ) => request<Lead>(`/api/leads/${id}/preview`, { method: "POST", body: json(body) }),
  sendEmail: (id: number) => request<Lead>(`/api/leads/${id}/send-email`, { method: "POST" }),
  testEmail: () => request<{ ok: boolean; message: string }>("/api/settings/test-email", { method: "POST" }),
  refreshLead: (id: number) => request<Lead>(`/api/leads/${id}/refresh`, { method: "POST" }),
  audit: (url: string) => request<AuditResult>("/api/audit", { method: "POST", body: json({ url }) }),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (values: Record<string, string>) =>
    request<Settings>("/api/settings", { method: "PUT", body: json(values) }),
  models: () =>
    request<{ models: string[]; automatic: string | null; error: string | null }>("/api/settings/models"),
  testAI: () =>
    request<{ ok: boolean; message: string; provider?: string; model?: string }>("/api/settings/test-ai", {
      method: "POST",
    }),
  clearSecret: (key: string) => request<Settings>(`/api/settings/${key}`, { method: "DELETE" }),
};

/** Download a file from a protected endpoint (plain links can't send the login token). */
export async function download(path: string, filename: string) {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
