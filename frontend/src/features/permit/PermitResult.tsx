import { Badge } from "@/components/ui/Badge";
import { ANSWER, EVIDENCE_STATUS, OUTCOME } from "./present";
import type { Evidence, PermitMatter } from "./types";
import styles from "./Permit.module.css";

function Refs({ ids }: { ids: string[] }) {
  if (!ids.length) return null;
  return (
    <span className={styles.refs}>
      {ids.map((id) => (
        <a key={id} href={`#evidence-${id}`} className={styles.ref} aria-label={`Evidence ${id}`}>
          {id}
        </a>
      ))}
    </span>
  );
}

export function PermitResult({
  matter,
  evidence,
  authorityName,
}: {
  matter: PermitMatter;
  evidence: Evidence[];
  authorityName: string | null;
}) {
  const authority = authorityName ?? "the competent authority";
  const draft = matter.draft;
  const outcome = OUTCOME[matter.state as keyof typeof OUTCOME];

  return (
    <div className={styles.result}>
      <div className={styles.resultHead}>
        {outcome && <Badge tone={outcome.tone}>{outcome.label}</Badge>}
        {draft && matter.state !== "VERIFIED" && <span className={styles.unverified}>Unverified draft</span>}
      </div>

      {matter.state === "VERIFIED" && (
        <p className={styles.meaning}>
          HABITA&apos;s assessment passed its evidence and verification checks. It is not a permit: approval rests
          with {authority}.
        </p>
      )}

      {(matter.state === "ESCALATE" || matter.state === "REJECTED") && matter.escalation_reason && (
        <p className={styles.escalation}>{matter.escalation_reason}</p>
      )}

      {draft && (
        <>
          <div className={styles.conclusion}>
            <p className={styles.answer}>{ANSWER[draft.conclusion.answer]}</p>
            <p className={styles.summary}>
              {draft.conclusion.summary} <Refs ids={draft.conclusion.evidence_ids} />
            </p>
          </div>

          {draft.conditions.length > 0 && (
            <div className={styles.conditions}>
              <h3 className={styles.conditionsTitle}>Before you proceed, confirm with {authority}</h3>
              <ul className={styles.list}>
                {draft.conditions.map((c) => (
                  <li key={c.item_key}>{c.text}</li>
                ))}
              </ul>
            </div>
          )}

          {draft.claims.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>Findings</h3>
              <ul className={styles.list}>
                {draft.claims.map((claim) => (
                  <li key={claim.claim_id}>
                    {claim.text} <Refs ids={claim.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft.procedure.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>Likely procedure</h3>
              <ol className={styles.steps}>
                {draft.procedure.map((p) => (
                  <li key={p.step}>
                    <span className={styles.stepName}>{p.step}</span> {p.description} <Refs ids={p.evidence_ids} />
                  </li>
                ))}
              </ol>
            </div>
          )}

          {draft.risks.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>Risks and uncertainties</h3>
              <ul className={styles.list}>
                {draft.risks.map((r) => (
                  <li key={r.text}>
                    {r.text} <Refs ids={r.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft.next_actions.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>Next actions</h3>
              <ul className={styles.list}>
                {draft.next_actions.map((a) => (
                  <li key={a.text}>
                    {a.text} <Refs ids={a.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {evidence.length > 0 && (
        <details className={styles.evidence}>
          <summary>Evidence ({evidence.length})</summary>
          <ol className={styles.evidenceList}>
            {evidence.map((e) => (
              <li key={e.evidence_id} id={`evidence-${e.evidence_id}`} className={styles.evidenceItem}>
                <p className={styles.evidenceHead}>
                  <span className={styles.ref}>{e.evidence_id}</span>
                  <span className={styles.evidenceTitle}>{e.source_title}</span>
                </p>
                <p className={styles.evidenceExcerpt}>{e.excerpt}</p>
                <p className={styles.evidenceMeta}>
                  {e.source_url ? (
                    <a href={e.source_url} target="_blank" rel="noopener noreferrer">
                      {e.source_reference}
                    </a>
                  ) : (
                    e.source_reference
                  )}{" "}
                  · {EVIDENCE_STATUS[e.verification_status]}
                </p>
              </li>
            ))}
          </ol>
        </details>
      )}

      <p className={styles.disclaimer}>
        Decision support, not legal advice. Confirm requirements with the competent authority before acting.
      </p>
    </div>
  );
}
