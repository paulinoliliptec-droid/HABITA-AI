import { Badge } from "@/components/ui/Badge";
import { useI18n } from "@/i18n/useI18n";
import { ANSWER, evidenceBasis, outcomeOf } from "./present";
import type { Evidence, PermitMatter } from "./types";
import styles from "./Permit.module.css";

function Refs({ ids }: { ids: string[] }) {
  const { t } = useI18n();
  if (!ids.length) return null;
  return (
    <span className={styles.refs}>
      {ids.map((id) => (
        <a key={id} href={`#evidence-${id}`} className={styles.ref} aria-label={t("Evidence {id}", { id })}>
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
  shown,
  note,
}: {
  matter: PermitMatter;
  evidence: Evidence[];
  authorityName: string | null;
  /** The text to show for an English text of the matter (itself in English). */
  shown: (text: string) => string;
  /** The label of a translated view: it says what was verified. */
  note: string | null;
}) {
  const { t, locale } = useI18n();
  const authority = authorityName ?? t("the competent authority");
  const draft = matter.draft;
  const outcome = outcomeOf(matter);
  const verified = matter.assessment_status === "verified_assessment";

  return (
    <div className={styles.result}>
      <div className={styles.resultHead}>
        {outcome && <Badge tone={outcome.tone}>{t(outcome.label)}</Badge>}
        {draft && !verified && <span className={styles.unverified}>{t("Unverified draft")}</span>}
      </div>

      {verified && (
        <p className={styles.meaning}>
          {t("HABITA's assessment passed its evidence and verification checks. It is not a permit: approval rests with {authority}.", { authority })}
        </p>
      )}
      {note && <p className={styles.translationNote}>{note}</p>}
      {matter.assessment_status === "superseded_assessment" && matter.outcome_note && (
        <p className={styles.escalation}>{shown(matter.outcome_note)}</p>
      )}

      {(matter.state === "ESCALATE" || matter.state === "REJECTED") && matter.escalation_reason && (
        <p className={styles.escalation}>{shown(matter.escalation_reason)}</p>
      )}

      {draft && (
        <>
          <div className={styles.conclusion}>
            <p className={styles.answer}>{t(ANSWER[draft.conclusion.answer])}</p>
            <p className={styles.summary}>
              {shown(draft.conclusion.summary)} <Refs ids={draft.conclusion.evidence_ids} />
            </p>
          </div>

          {draft.conditions.length > 0 && (
            <div className={styles.conditions}>
              <h3 className={styles.conditionsTitle}>{t("Before you proceed, confirm with {authority}", { authority })}</h3>
              <ul className={styles.list}>
                {draft.conditions.map((c) => (
                  <li key={c.item_key}>{shown(c.text)}</li>
                ))}
              </ul>
            </div>
          )}

          {draft.claims.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>{t("Findings")}</h3>
              <ul className={styles.list}>
                {draft.claims.map((claim) => (
                  <li key={claim.claim_id}>
                    {shown(claim.text)} <Refs ids={claim.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft.procedure.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>{t("Likely procedure")}</h3>
              <ol className={styles.steps}>
                {draft.procedure.map((p) => (
                  <li key={p.step}>
                    <span className={styles.stepName}>{shown(p.step)}</span> {shown(p.description)} <Refs ids={p.evidence_ids} />
                  </li>
                ))}
              </ol>
            </div>
          )}

          {draft.risks.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>{t("Risks and uncertainties")}</h3>
              <ul className={styles.list}>
                {draft.risks.map((r) => (
                  <li key={r.text}>
                    {shown(r.text)} <Refs ids={r.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {draft.next_actions.length > 0 && (
            <div className={styles.block}>
              <h3 className={styles.blockTitle}>{t("Next actions")}</h3>
              <ul className={styles.list}>
                {draft.next_actions.map((a) => (
                  <li key={a.text}>
                    {shown(a.text)} <Refs ids={a.evidence_ids} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {evidence.length > 0 && (
        <details className={styles.evidence}>
          <summary>{t("Evidence ({n})", { n: evidence.length })}</summary>
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
                  · {evidenceBasis(e, t, locale)}
                </p>
              </li>
            ))}
          </ol>
        </details>
      )}

      <p className={styles.disclaimer}>
        {t("Decision support, not legal advice. Confirm requirements with the competent authority before acting.")}
      </p>
    </div>
  );
}
