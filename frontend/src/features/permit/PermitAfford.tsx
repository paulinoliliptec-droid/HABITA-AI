"use client";

import { inePeriod } from "./inePeriod";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { reportChanged } from "@/features/report/api";
import { msg } from "@/i18n/core";
import { useI18n } from "@/i18n/useI18n";
import { ApiError } from "@/lib/api";
import { getAfford, saveAfford, type AffordFigure, type AffordInputs, type AffordReport } from "./api";
import styles from "./Permit.module.css";

const FIELDS = [
  { key: "area_m2", label: msg("Area (m²)") },
  { key: "quote_low", label: msg("Lowest quote you have (€)") },
  { key: "quote_high", label: msg("Highest quote you have (€)") },
  { key: "budget", label: msg("Your budget (€)") },
  { key: "rate_percent", label: msg("Annual interest rate (%)") },
  { key: "years", label: msg("Loan term (years)") },
  { key: "down_payment", label: msg("Down payment (€)") },
] as const;
const SCENARIO = { lower: msg("Lower scenario"), likely: msg("Likely scenario"), higher: msg("Higher scenario") } as const;
const EMPTY: AffordInputs = {
  area_m2: null, property_type: null, quote_low: null, quote_high: null, budget: null, rate_percent: null, years: null,
  down_payment: null,
};

/** HR-011: every number is computed by HABITA from named sources and the user's own figures; an estimate only. */
export function PermitAfford({ matterId, token }: { matterId: string; token: string }) {
  const { lang, t } = useI18n();
  const id = useId();
  const [inputs, setInputs] = useState<AffordInputs>(EMPTY);
  const [result, setResult] = useState<AffordReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const money = (v: number) =>
    new Intl.NumberFormat(lang === "pt" ? "pt-PT" : "en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);

  useEffect(() => {
    let cancelled = false;
    getAfford(matterId, token)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setInputs(r.inputs);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [matterId, token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await saveAfford(matterId, token, inputs));
      reportChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const span = (lo: number, hi: number) => (lo === hi ? money(lo) : `${money(lo)} – ${money(hi)}`);
  const amount = (f: AffordFigure) =>
    f.per_m2_low === null || f.per_m2_high === null
      ? span(f.low, f.high)
      : t("{per} per m², {total} in total", { per: span(f.per_m2_low, f.per_m2_high), total: span(f.low, f.high) });

  return (
    <div className={styles.files}>
      <h3 className={styles.filesTitle}>{t("Costs, financing and price")}</h3>
      <p className={styles.filesPurpose}>
        {t("Enter what you know to see what the works may cost, how a loan could look and what similar homes are worth here.")}
      </p>

      <form className={styles.affordForm} onSubmit={submit}>
        <label className={styles.fieldLabel} htmlFor={`${id}-type`}>
          {t("Type of property")}
        </label>
        <select
          id={`${id}-type`}
          value={inputs.property_type ?? ""}
          onChange={(e) => setInputs({ ...inputs, property_type: (e.target.value || null) as AffordInputs["property_type"] })}
        >
          <option value="">{t("Not specified")}</option>
          <option value="apartment">{t("Apartment")}</option>
          <option value="house">{t("House")}</option>
        </select>
        {FIELDS.map((f) => (
          <div key={f.key} className={styles.affordField}>
            <label className={styles.fieldLabel} htmlFor={`${id}-${f.key}`}>
              {t(f.label)}
            </label>
            <input
              id={`${id}-${f.key}`}
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              value={inputs[f.key] ?? ""}
              onChange={(e) => setInputs({ ...inputs, [f.key]: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </div>
        ))}
        <Button type="submit" disabled={busy}>
          {t("Calculate")}
        </Button>
      </form>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className={styles.affordResult}>
          {result.costs.length > 0 && (
            <div>
              <p className={styles.fieldLabel}>{t("Cost of the works")}</p>
              <ul className={styles.affordList}>
                {result.costs.map((f) => (
                  <li key={f.label}>
                    <strong>{amount(f)}</strong> · {t(f.label)}
                    <br />
                    <span className={styles.fieldHint}>
                      {t(f.source)}
                      {f.author ? ` · ${t(f.author)}` : ""}
                      {f.as_of ? ` · ${inePeriod(f.as_of, lang)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.costs_note && <p className={styles.fieldHint}>{t(result.costs_note)}</p>}

          {result.scenarios.length > 0 && (
            <div>
              <p className={styles.fieldLabel}>{t("Scenarios")}</p>
              <ul className={styles.affordList}>
                {result.scenarios.map((s) => (
                  <li key={s.key}>
                    <strong>{t(SCENARIO[s.key])}: {money(s.cost)}</strong>
                    {s.monthly_payment !== null && ` · ${t("about {payment} a month", { payment: money(s.monthly_payment) })}`}
                    {s.within_budget !== null && ` · ${s.within_budget ? t("within your budget") : t("above your budget")}`}
                    <br />
                    <span className={styles.fieldHint}>{s.assumptions.map((x) => t(x)).join(" ")}</span>
                  </li>
                ))}
              </ul>
              <p className={styles.fieldHint}>
                {t("What would change it:")} {result.scenarios[0].moves_it.map((x) => t(x)).join(" ")}
              </p>
            </div>
          )}
          {result.financing_note && <p className={styles.fieldHint}>{t(result.financing_note)}</p>}
          {result.scenarios.some((s) => s.monthly_payment !== null) && <p className={styles.fieldHint}>{t(result.formula)}</p>}

          <div>
            <p className={styles.fieldLabel}>{t("What homes are worth here")}</p>
            {result.valuation.length > 0 ? (
              <ul className={styles.affordList}>
                {result.valuation.map((f) => (
                  <li key={f.label}>
                    <strong>{amount(f)}</strong> · {t(f.label)}
                    <br />
                    <span className={styles.fieldHint}>
                      {t(f.source)}
                      {f.author ? ` · ${t(f.author)}` : ""}
                      {f.as_of ? ` · ${inePeriod(f.as_of, lang)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.fieldHint}>{result.valuation_note && t(result.valuation_note)}</p>
            )}
            {result.valuation.length > 0 && result.valuation_note && (
              <p className={styles.fieldHint}>{t(result.valuation_note)}</p>
            )}
            {result.valuation.length > 0 && result.inputs.area_m2 !== null && (
              <p className={styles.fieldHint}>
                {t("Totals use the area you declared: {area} m². They are market estimates, not a valuation of this property.", {
                  area: String(result.inputs.area_m2),
                })}
              </p>
            )}
          </div>

          <p className={styles.fieldHint}>{t(result.fees_note)}</p>
          <p className={styles.affordDisclaimer}>{t(result.disclaimer)}</p>
        </div>
      )}
    </div>
  );
}
