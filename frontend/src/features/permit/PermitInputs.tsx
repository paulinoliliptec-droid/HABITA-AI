"use client";

import { Fragment, useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { INPUT_CHOICES } from "./present";
import type { MissingInput } from "./types";
import styles from "./Permit.module.css";

const OTHER = "__other__";

export function PermitInputs({
  items,
  busy,
  onSubmit,
}: {
  items: MissingInput[];
  busy: boolean;
  onSubmit: (answers: Record<string, string>) => void;
}) {
  const formId = useId();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [others, setOthers] = useState<Record<string, string>>({});

  function valueOf(key: string): string {
    const raw = answers[key] ?? "";
    if (raw !== OTHER) return raw.trim();
    const detail = (others[key] ?? "").trim();
    return detail ? `${INPUT_CHOICES[key]?.other ?? "Other"}: ${detail}` : "";
  }

  const complete = items.every((item) => valueOf(item.input_key).length > 0);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!complete || busy) return;
    onSubmit(Object.fromEntries(items.map((item) => [item.input_key, valueOf(item.input_key)])));
  }

  return (
    <form className={styles.inputs} onSubmit={submit}>
      <p className={styles.inputsIntro}>
        These facts can&apos;t be obtained from public sources. Everything else HABITA checks itself.
      </p>
      {items.map((item) => {
        const id = `${formId}-${item.input_key}`;
        const choices = INPUT_CHOICES[item.input_key];
        if (choices) {
          return (
            <fieldset key={item.input_key} className={styles.field} aria-describedby={`${id}-why`}>
              <legend className={styles.fieldLabel}>{item.question}</legend>
              <div className={styles.choices}>
                {[...choices.options, ...(choices.other ? [OTHER] : [])].map((option) => (
                  <Fragment key={option}>
                    <label className={styles.choice}>
                      <input
                        type="radio"
                        name={id}
                        value={option}
                        checked={answers[item.input_key] === option}
                        disabled={busy}
                        onChange={() => setAnswers((a) => ({ ...a, [item.input_key]: option }))}
                      />
                      {option === OTHER ? choices.other : option}
                    </label>
                    {/* Revealed directly under "Other use" so the user can specify it. */}
                    {option === OTHER && answers[item.input_key] === OTHER && (
                      <input
                        type="text"
                        className={`${styles.textInput} ${styles.otherInput}`}
                        aria-label={`${choices.other}: please specify`}
                        placeholder="Please specify"
                        maxLength={300}
                        autoFocus
                        value={others[item.input_key] ?? ""}
                        disabled={busy}
                        onChange={(e) => setOthers((o) => ({ ...o, [item.input_key]: e.target.value }))}
                      />
                    )}
                  </Fragment>
                ))}
              </div>
              <p id={`${id}-why`} className={styles.fieldHint}>
                {item.reason}
              </p>
            </fieldset>
          );
        }
        return (
          <div key={item.input_key} className={styles.field}>
            <label htmlFor={id} className={styles.fieldLabel}>
              {item.question}
            </label>
            <textarea
              id={id}
              className={styles.textarea}
              rows={2}
              maxLength={2000}
              value={answers[item.input_key] ?? ""}
              disabled={busy}
              aria-describedby={`${id}-why`}
              onChange={(e) => setAnswers((a) => ({ ...a, [item.input_key]: e.target.value }))}
            />
            <p id={`${id}-why`} className={styles.fieldHint}>
              {item.reason}
            </p>
          </div>
        );
      })}
      <div className={styles.submitRow}>
        <Button type="submit" loading={busy} disabled={!complete} aria-describedby={complete ? undefined : `${formId}-hint`}>
          Continue investigation
        </Button>
        {!complete && (
          <p id={`${formId}-hint`} className={styles.fieldHint}>
            Answer the required questions to continue.
          </p>
        )}
      </div>
    </form>
  );
}
