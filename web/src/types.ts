export type Status = "new" | "contacted" | "replied" | "meeting" | "won" | "lost" | "skip";

export const STATUSES: Status[] = ["new", "contacted", "replied", "meeting", "won", "lost", "skip"];

export const STATUS_LABEL: Record<Status, string> = {
  new: "New",
  contacted: "Contacted",
  replied: "Replied",
  meeting: "Meeting",
  won: "Won",
  lost: "Lost",
  skip: "Skip",
};

export interface Finding {
  id: string;
  impact: 1 | 2 | 3;
  title: string;
  detail: string;
  fix: string;
}

export interface Lead {
  id: number;
  name: string;
  email: string;
  website: string;
  phone: string;
  category: string;
  city: string;
  address: string;
  maps_url: string;
  facebook_search: string;
  reviews: string;
  rating: string;
  has_website: boolean;
  reachable: boolean | null;
  site_score: number | null;
  tier: string;
  qual_score: number | null;
  reasons: string;
  top_issue: string;
  findings: Finding[];
  report_token: string;
  preview_token: string;
  preview_notes: string;
  preview_source: string;
  subject: string;
  body: string;
  angle: string;
  pitch_source: string;
  message: string;
  status: Status;
  notes: string;
  search_query: string;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  done: number;
  total: number;
  error: string | null;
  with_website: number;
  no_website: number;
}

export interface Stats {
  total: number;
  with_website: number;
  no_website: number;
  tier_a: number;
  by_status: Record<Status, number>;
  angles: { angle: string; sent: number; replies: number }[];
}

export interface Settings {
  sender_name: string;
  sender_company: string;
  sender_email: string;
  sender_address: string;
  report_base_url: string;
  use_ai: string;
  google_api_key_set: boolean;
  anthropic_api_key_set: boolean;
}

export interface AuditResult {
  url: string;
  final_url: string | null;
  score: number;
  reachable: boolean;
  error: string | null;
  page_title: string | null;
  load_seconds: number | null;
  findings: Finding[];
}
