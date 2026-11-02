"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Section } from "@/components/ui/Section";
import { reportChanged } from "@/features/report/api";
import { setLanguage, useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import {
  continueMatter,
  createMatter,
  getEvidence,
  getMatter,
  getTranslation,
  permitStatus,
  supplyInputs,
  type MatterTranslation,
} from "./api";
import { forgetMatter, recallMatter, rememberMatter } from "./capability";
import { PermitAfford } from "./PermitAfford";
import { PermitConcepts } from "./PermitConcepts";
import { PermitFiles } from "./PermitFiles";
import { PermitInputs } from "./PermitInputs";
import { PermitProgress } from "./PermitProgress";
import { PermitResult } from "./PermitResult";
import { INTENT_LABEL, SUGGESTED_QUESTIONS, sourcesLine } from "./present";
import { STABLE_STATES, type Evidence, type PermitIntent, type PermitMatter } from "./types";
import styles from "./Permit.module.css";
import { DictateButton } from "@/features/voice/DictateButton";
import type { AreaId } from "@/features/property/areas";

const POLL_MS = 1500;

export function PermitSection({
  propertyId,
  authorityName,
  area = "question",
  onGo,
}: {
  propertyId: string;
  authorityName: string | null;
  /** The workspace area shown; the others stay mounted but hidden, so nothing in progress is lost. */
  area?: AreaId;
  onGo?: (area: AreaId) => void;
}) {
  const { lang, t } = useI18n();
  const [available, setAvailable] = useState<boolean | null>(null);
  const [matter, setMatter] = useState<PermitMatter | null>(null);
  // The capability for this browser's own matter; never shared, never in the URL.
  const [token, setToken] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [choosing, setChoosing] = useState(false);
  // Bumped when a file is added or deleted, so the concepts panel sees the new photo at once.
  const [filesVersion, setFilesVersion] = useState(0);
  // Keyed like the evidence below: a translation read for another matter, state or language is never shown.
  const [translation, setTranslation] = useState<{ key: string; data: MatterTranslation | null } | null>(null);

  // Resume only the matter this browser created for this property (its capability is stored locally).
  useEffect(() => {
    let cancelled = false;
    const own = recallMatter(propertyId);
    const restore = own
      ? getMatter(own.matterId, own.token).catch((err: unknown) => {
          // Rejected or gone: forget it rather than retrying with a dead capability.
          if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
            forgetMatter(propertyId);
            reportChanged();
          }
          return null;
        })
      : Promise.resolve(null);
    Promise.all([permitStatus(), restore])
      .then(([status, restored]) => {
        if (cancelled) return;
        setAvailable(status.available);
        setMatter(restored);
        setToken(restored && own ? own.token : null);
      })
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
    };
  }, [propertyId]);

  // Evidence is loaded whenever the matter settles.
  const matterId = matter?.matter_id;
  const settledState = matter && STABLE_STATES.has(matter.state) ? matter.state : null;
  useEffect(() => {
    if (!matterId || !settledState || !token) return;
    getEvidence(matterId, token).then(setEvidence).catch(() => setEvidence([]));
  }, [matterId, settledState, token]);

  // The map's post-its and the PDF read the same report; refresh them when the matter settles.
  useEffect(() => {
    if (matterId && settledState) reportChanged();
  }, [matterId, settledState]);

  // What was verified stays the English text in the matter; Portuguese is a labelled view of it, read when it settles.
  const revision = matter?.draft?.revision;
  const translationKey = `${matterId}:${settledState}:${revision}:${lang}`;
  useEffect(() => {
    if (!matterId || !settledState || !token || lang === "en") return;
    getTranslation(matterId, token, lang)
      .then((data) => setTranslation({ key: translationKey, data }))
      .catch(() => setTranslation({ key: translationKey, data: null }));
  }, [matterId, settledState, token, lang, revision, translationKey]);
  const current = translation?.key === translationKey ? translation : null;
  const shown = (text: string) => current?.data?.texts[text] ?? text;
  const note =
    lang === "en" || !current ? null : (current.data?.note ?? t("Translation is unavailable right now: the original English text is shown."));

  const poller = useRef<ReturnType<typeof setInterval> | null>(null);

  const advance = useCallback(async (id: string, capability: string) => {
    setRunning(true);
    setError(null);
    // The run holds one request open; poll alongside it to show the operational state.
    poller.current = setInterval(() => {
      getMatter(id, capability).then(setMatter).catch(() => {});
    }, POLL_MS);
    try {
      setMatter(await continueMatter(id, capability));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("The investigation was interrupted. You can resume it."));
      getMatter(id, capability).then(setMatter).catch(() => {});
    } finally {
      if (poller.current) clearInterval(poller.current);
      poller.current = null;
      setRunning(false);
    }
  }, [t]);

  useEffect(() => () => {
    if (poller.current) clearInterval(poller.current);
  }, []);

  async function ask(question: string, intent?: PermitIntent) {
    setError(null);
    setChoosing(false);
    try {
      const created = await createMatter(propertyId, question, intent);
      if (created.detected_language) setLanguage(created.detected_language); // answers follow the language asked in
      rememberMatter(propertyId, { matterId: created.matter.matter_id, token: created.access_token });
      reportChanged(); // the map and the PDF now follow the new matter
      setToken(created.access_token);
      setMatter(created.matter);
      setEvidence([]);
      setAsking(false);
      await advance(created.matter.matter_id, created.access_token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
    }
  }

  async function answer(answers: Record<string, string>) {
    if (!matter || !token) return;
    setRunning(true);
    try {
      const updated = await supplyInputs(matter.matter_id, token, answers);
      setMatter(updated);
      await advance(updated.matter_id, token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
      setRunning(false);
    }
  }

  const ready = Boolean(matter && token && !running);
  // Photos, concepts and costs belong to a question: until there is one, their area says how to start.
  const needQuestion = available === false ? (
    <Notice title={t("Permit intelligence isn't available yet")}>
      {t("The reasoning model isn't configured on this server. Property and jurisdiction data remain available.")}
    </Notice>
  ) : (
    <Notice
      title={t("Start with a question")}
      action={
        onGo && (
          <Button onClick={() => onGo("question")}>{t("Ask a question")}</Button>
        )
      }
    >
      {t("Photos and plans, before/after concepts and costs are attached to a question about this property. Ask it first, then come back here.")}
    </Notice>
  );

  return (
    <>
    <div role="tabpanel" id="area-question" aria-labelledby="area-tab-question" hidden={area !== "question"}>
    <Section label={t("Permit intelligence")} id="permit">
      {available === false ? (
        <Notice title={t("Permit intelligence isn't available yet")}>
          {t("The reasoning model isn't configured on this server. Property and jurisdiction data remain available.")}
        </Notice>
      ) : !matter || asking ? (
        <GoalForm onAsk={ask} onCancel={matter ? () => setAsking(false) : undefined} />
      ) : (
        <div className={styles.matter}>
          <p className={styles.goal}>{matter.question}</p>
          {matter.intent && matter.intent !== "out_of_scope" && (
            <p className={styles.worked}>{t("Understood as: {type}", { type: t(INTENT_LABEL[matter.intent]) })}</p>
          )}
          <PermitProgress matter={matter} running={running} />

          {matter.state === "NEEDS_INPUT" && !running && evidence.length > 0 && (
            <p className={styles.worked}>
              {sourcesLine(
                evidence.filter((e) => e.source_type !== "user_statement").length,
                matter.missing_inputs.length,
                t,
              )}
            </p>
          )}
          {matter.state === "NEEDS_INPUT" && !running && (
            <PermitInputs key={matter.missing_inputs.map((m) => m.input_key).join()} items={matter.missing_inputs} busy={running} onSubmit={answer} shown={shown} />
          )}
          {(matter.state === "VERIFIED" || matter.state === "ESCALATE" || matter.state === "REJECTED" ||
            matter.state === "NEEDS_INPUT") && (
            <PermitResult matter={matter} evidence={evidence} authorityName={authorityName} shown={shown} note={note} />
          )}

          {ready && onGo && (
            <div className={styles.next}>
              <p className={styles.fieldHint}>{t("Next, for this question:")}</p>
              <div className={styles.actions}>
                <Button variant="secondary" onClick={() => onGo("documents")}>
                  {t("Add photos & plans")}
                </Button>
                <Button variant="secondary" onClick={() => onGo("concepts")}>
                  {t("See before / after")}
                </Button>
                <Button variant="secondary" onClick={() => onGo("costs")}>
                  {t("Estimate costs")}
                </Button>
              </div>
            </div>
          )}

          {STABLE_STATES.has(matter.state) && !running && (choosing || matter.intent === "out_of_scope") && (
            <div className={styles.suggestions}>
              <p className={styles.fieldHint}>{t("Not what you asked? Choose the type and HABITA starts again.")}</p>
              {(Object.keys(INTENT_LABEL) as PermitIntent[]).map((intent) => (
                <button key={intent} type="button" className={styles.suggestion} onClick={() => ask(matter.question, intent)}>
                  {t(INTENT_LABEL[intent])}
                </button>
              ))}
            </div>
          )}

          <div className={styles.actions}>
            {matter.state === "FAILED" && !running && (
              <Button variant="secondary" onClick={() => token && advance(matter.matter_id, token)}>
                {t("Resume investigation")}
              </Button>
            )}
            {!STABLE_STATES.has(matter.state) && !running && (
              <Button variant="secondary" onClick={() => token && advance(matter.matter_id, token)}>
                {t("Continue")}
              </Button>
            )}
            {STABLE_STATES.has(matter.state) && !running && (
              <Button variant="ghost" onClick={() => setAsking(true)}>
                {t("Ask another question")}
              </Button>
            )}
            {STABLE_STATES.has(matter.state) && !running && matter.intent && matter.intent !== "out_of_scope" && !choosing && (
              <Button variant="ghost" onClick={() => setChoosing(true)}>
                {t("Choose the type")}
              </Button>
            )}
          </div>
        </div>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </Section>
    </div>
    <div role="tabpanel" id="area-documents" aria-labelledby="area-tab-documents" hidden={area !== "documents"}>
      {ready && matter && token ? (
        <PermitFiles matterId={matter.matter_id} token={token} onChange={() => setFilesVersion((n) => n + 1)} />
      ) : (
        needQuestion
      )}
    </div>
    <div role="tabpanel" id="area-concepts" aria-labelledby="area-tab-concepts" hidden={area !== "concepts"}>
      {ready && matter && token ? (
        <PermitConcepts matterId={matter.matter_id} token={token} filesVersion={filesVersion} />
      ) : (
        needQuestion
      )}
    </div>
    <div role="tabpanel" id="area-costs" aria-labelledby="area-tab-costs" hidden={area !== "costs"}>
      {ready && matter && token ? <PermitAfford matterId={matter.matter_id} token={token} /> : needQuestion}
    </div>
    </>
  );
}

function GoalForm({ onAsk, onCancel }: { onAsk: (question: string) => Promise<void>; onCancel?: () => void }) {
  const { t } = useI18n();
  const id = useId();
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent, value = question) {
    event.preventDefault();
    if (value.trim().length < 8 || submitting) return;
    setSubmitting(true);
    await onAsk(value.trim());
    setSubmitting(false);
  }

  return (
    <form className={styles.goalForm} onSubmit={submit}>
      <label htmlFor={id} className={styles.fieldLabel}>
        {t("Ask what this property allows")}
      </label>
      <textarea
        id={id}
        className={styles.textarea}
        rows={2}
        maxLength={500}
        placeholder={t("e.g. Can I convert this property into two residential units?")}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <DictateButton
        disabled={submitting}
        onText={(text) => setQuestion((q) => (q.trim() ? `${q.trim()} ${text}` : text).slice(0, 500))}
      />
      <div className={styles.suggestions}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <button key={q} type="button" className={styles.suggestion} onClick={() => setQuestion(t(q))}>
            {t(q)}
          </button>
        ))}
      </div>
      <div className={styles.actions}>
        <Button type="submit" size="lg" loading={submitting} disabled={question.trim().length < 8}>
          {t("Investigate")}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
        )}
      </div>
      <p className={styles.fieldHint}>
        {t("HABITA plans a checklist, gathers evidence from the jurisdiction's sources, drafts an answer and has it independently verified. Powered by Meta Muse Spark.")}
      </p>
    </form>
  );
}
