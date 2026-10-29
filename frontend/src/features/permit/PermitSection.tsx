"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Section } from "@/components/ui/Section";
import { reportChanged } from "@/features/report/api";
import { ApiError } from "@/lib/api";
import { continueMatter, createMatter, getEvidence, getMatter, permitStatus, supplyInputs } from "./api";
import { forgetMatter, recallMatter, rememberMatter } from "./capability";
import { PermitInputs } from "./PermitInputs";
import { PermitProgress } from "./PermitProgress";
import { PermitResult } from "./PermitResult";
import { SUGGESTED_QUESTIONS, sourcesLine } from "./present";
import { STABLE_STATES, type Evidence, type PermitMatter } from "./types";
import styles from "./Permit.module.css";

const POLL_MS = 1500;

export function PermitSection({ propertyId, authorityName }: { propertyId: string; authorityName: string | null }) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [matter, setMatter] = useState<PermitMatter | null>(null);
  // The capability for this browser's own matter; never shared, never in the URL.
  const [token, setToken] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

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
      setError(err instanceof ApiError ? err.message : "The investigation was interrupted. You can resume it.");
      getMatter(id, capability).then(setMatter).catch(() => {});
    } finally {
      if (poller.current) clearInterval(poller.current);
      poller.current = null;
      setRunning(false);
    }
  }, []);

  useEffect(() => () => {
    if (poller.current) clearInterval(poller.current);
  }, []);

  async function ask(question: string) {
    setError(null);
    try {
      const created = await createMatter(propertyId, question);
      rememberMatter(propertyId, { matterId: created.matter.matter_id, token: created.access_token });
      reportChanged(); // the map and the PDF now follow the new matter
      setToken(created.access_token);
      setMatter(created.matter);
      setEvidence([]);
      setAsking(false);
      await advance(created.matter.matter_id, created.access_token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
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
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setRunning(false);
    }
  }

  return (
    <Section label="Permit intelligence" id="permit">
      {available === false ? (
        <Notice title="Permit intelligence isn't available yet">
          The reasoning model isn&apos;t configured on this server. Property and jurisdiction data remain available.
        </Notice>
      ) : !matter || asking ? (
        <GoalForm onAsk={ask} onCancel={matter ? () => setAsking(false) : undefined} />
      ) : (
        <div className={styles.matter}>
          <p className={styles.goal}>{matter.question}</p>
          <PermitProgress matter={matter} running={running} />

          {matter.state === "NEEDS_INPUT" && !running && evidence.length > 0 && (
            <p className={styles.worked}>
              {sourcesLine(
                evidence.filter((e) => e.source_type !== "user_statement").length,
                matter.missing_inputs.length,
              )}
            </p>
          )}
          {matter.state === "NEEDS_INPUT" && !running && (
            <PermitInputs key={matter.missing_inputs.map((m) => m.input_key).join()} items={matter.missing_inputs} busy={running} onSubmit={answer} />
          )}
          {(matter.state === "VERIFIED" || matter.state === "ESCALATE" || matter.state === "REJECTED" ||
            matter.state === "NEEDS_INPUT") && (
            <PermitResult matter={matter} evidence={evidence} authorityName={authorityName} />
          )}

          <div className={styles.actions}>
            {matter.state === "FAILED" && !running && (
              <Button variant="secondary" onClick={() => token && advance(matter.matter_id, token)}>
                Resume investigation
              </Button>
            )}
            {!STABLE_STATES.has(matter.state) && !running && (
              <Button variant="secondary" onClick={() => token && advance(matter.matter_id, token)}>
                Continue
              </Button>
            )}
            {STABLE_STATES.has(matter.state) && !running && (
              <Button variant="ghost" onClick={() => setAsking(true)}>
                Ask another question
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
  );
}

function GoalForm({ onAsk, onCancel }: { onAsk: (question: string) => Promise<void>; onCancel?: () => void }) {
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
        Ask what this property allows
      </label>
      <textarea
        id={id}
        className={styles.textarea}
        rows={2}
        maxLength={500}
        placeholder="e.g. Can I convert this property into two residential units?"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <div className={styles.suggestions}>
        {SUGGESTED_QUESTIONS.map((q) => (
          <button key={q} type="button" className={styles.suggestion} onClick={() => setQuestion(q)}>
            {q}
          </button>
        ))}
      </div>
      <div className={styles.actions}>
        <Button type="submit" loading={submitting} disabled={question.trim().length < 8}>
          Investigate
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <p className={styles.fieldHint}>
        HABITA plans a checklist, gathers evidence from the jurisdiction&apos;s sources, drafts an answer and has it
        independently verified. Powered by Meta Muse Spark.
      </p>
    </form>
  );
}
