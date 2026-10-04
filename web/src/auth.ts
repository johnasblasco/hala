import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";

// Login is only active when the server says so (/api/config). Running locally
// with `hala serve` and no Supabase settings, there's no login at all.

let client: SupabaseClient | null = null;

export interface AuthConfig {
  supabase_url: string;
  anon_key: string;
}

export async function loadAuthConfig(): Promise<AuthConfig | null> {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error(`Couldn't reach the server (${res.status})`);
  const cfg = (await res.json()).auth as AuthConfig | null;
  if (cfg && !client) client = createClient(cfg.supabase_url, cfg.anon_key);
  return cfg;
}

export function supabase(): SupabaseClient | null {
  return client;
}

export async function accessToken(): Promise<string | null> {
  if (!client) return null;
  const { data } = await client.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function currentSession(): Promise<Session | null> {
  if (!client) return null;
  return (await client.auth.getSession()).data.session;
}

export async function signIn(email: string, password: string) {
  if (!client) throw new Error("Login isn't configured");
  const { error } = await client.auth.signInWithPassword({ email, password });
  if (error) throw new Error(error.message);
}

export async function signOut() {
  await client?.auth.signOut();
}
