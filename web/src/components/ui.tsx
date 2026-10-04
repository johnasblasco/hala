import { useState } from "react";
import type { Finding, Status } from "../types";
import { STATUS_LABEL } from "../types";

export function ScoreBadge({ score, reachable }: { score: number | null; reachable?: boolean | null }) {
  if (score === null || score === undefined) return <span className="muted">—</span>;
  if (reachable === false) return <span className="score score-bad">Down</span>;
  const cls = score < 50 ? "score-bad" : score < 80 ? "score-ok" : "score-good";
  return <span className={`score ${cls}`}>{score}</span>;
}

export function TierBadge({ tier }: { tier: string }) {
  if (!tier) return <span className="muted">—</span>;
  return <span className={`tier tier-${tier}`}>{tier === "skip" ? "Skip" : tier}</span>;
}

export function StatusPill({ status }: { status: Status }) {
  return <span className={`pill pill-${status}`}>{STATUS_LABEL[status]}</span>;
}

const IMPACT_LABEL = { 3: "Costing customers", 2: "Hurting trust", 1: "Quick win" } as const;

export function FindingList({ findings }: { findings: Finding[] }) {
  if (!findings.length) return <p className="muted">No issues found. This site is in good shape.</p>;
  return (
    <ul className="findings">
      {findings.map((f) => (
        <li key={f.id} className={`finding impact-${f.impact}`}>
          <span className="finding-tag">{IMPACT_LABEL[f.impact]}</span>
          <strong>{f.title}</strong>
          <p>{f.detail}</p>
          <p className="fix">
            <b>Fix:</b> {f.fix}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function CopyButton({
  text,
  label = "Copy",
  onCopied,
}: {
  text: string;
  label?: string;
  onCopied?: () => void;
}) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-small"
      disabled={!text}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        onCopied?.();
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "Copied ✓" : label}
    </button>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="alert alert-error">{error}</div>;
}
