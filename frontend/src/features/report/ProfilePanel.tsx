"use client";

import { useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useI18n } from "@/i18n/useI18n";
import { GROUPS, groupOf, profileCounts, type ProfileGroup } from "./profile";
import type { PermitReport } from "./types";
import { useModal } from "./useModal";
import styles from "./ProfilePanel.module.css";

const ICONS: Record<ProfileGroup, IconName> = { official: "landmark", observation: "pin", declaration: "person", unconfirmed: "clock" };

/** HR-008: what is known about the property and who said it, from the same report as the post-its and the PDF. */
export function ProfilePanel({ report, onClose }: { report: PermitReport; onClose: () => void }) {
  const { t, locale } = useI18n();
  const dialog = useRef<HTMLDivElement>(null);
  useModal(dialog, onClose);
  const items = report.profile;
  const counts = useMemo(() => profileCounts(report), [report]);
  const [filter, setFilter] = useState<ProfileGroup | null>(null);
  const [selected, setSelected] = useState(0);
  const shown = items.map((item, index) => ({ item, index })).filter(({ item }) => !filter || groupOf(item) === filter);
  const item = items[selected];

  function choose(group: ProfileGroup) {
    const next = filter === group ? null : group;
    setFilter(next);
    const first = items.findIndex((i) => !next || groupOf(i) === next);
    if (first >= 0) setSelected(first);
  }

  return createPortal(
    <div ref={dialog} className={styles.overlay} role="dialog" aria-modal="true" aria-label={t("Property profile")}>
      <header className={styles.header}>
        <div>
          <h2 className={styles.title}>{t("Property profile")}</h2>
          <p className={styles.subtitle}>{report.property.address}</p>
          <p className={styles.subtitle}>
            {t("Who said what about this property. Only a registered official source makes a fact official.")}
          </p>
        </div>
        <Button variant="secondary" onClick={onClose} autoFocus>
          {t("Close")}
        </Button>
      </header>

      <div className={styles.summary}>
        {GROUPS.map((g) => (
          <button key={g.id} type="button" className={styles.count} data-group={g.id} aria-pressed={filter === g.id} onClick={() => choose(g.id)}>
            <Icon name={ICONS[g.id]} />
            <strong>{counts[g.id]}</strong>
            <span>{t(g.label)}</span>
          </button>
        ))}
      </div>

      <div className={styles.body}>
        <ul className={styles.list}>
          {shown.map(({ item: entry, index }) => (
            <li key={index}>
              <button type="button" className={styles.item} data-group={groupOf(entry)} aria-pressed={index === selected} onClick={() => setSelected(index)}>
                <Icon name={ICONS[groupOf(entry)]} size={18} />
                <span className={styles.itemText}>
                  <span className={styles.itemLabel}>{entry.label}</span>
                  <span className={styles.itemValue}>{entry.value ?? t("Not confirmed")}</span>
                </span>
                {entry.conflict && <Icon name="alert" size={18} className={styles.conflictIcon} />}
              </button>
            </li>
          ))}
          {shown.length === 0 && <li className={styles.empty}>{t("Nothing in this group.")}</li>}
        </ul>

        {item && (
          <aside className={styles.detail} aria-live="polite">
            <p className={styles.kind} data-group={groupOf(item)}>
              {t(GROUPS.find((g) => g.id === groupOf(item))!.label)}
            </p>
            <h3 className={styles.detailTitle}>{item.label}</h3>
            <p className={styles.detailValue}>{item.value ?? t("Not confirmed")}</p>
            {item.conflict && <p className={styles.conflict}>{t("The sources disagree.")}</p>}
            {item.kind === "declaration" && <p className={styles.line}>{t("A declaration is your own statement. HABITA has not verified it.")}</p>}
            <dl className={styles.facts}>
              <dt>{item.value === null ? t("Where to confirm") : t("Origin")}</dt>
              <dd>{item.origin}</dd>
              {item.as_of && (
                <>
                  <dt>{t("Date")}</dt>
                  <dd>{new Date(item.as_of).toLocaleDateString(locale)}</dd>
                </>
              )}
              {item.precision && (
                <>
                  <dt>{t("Precision or version")}</dt>
                  <dd>{item.precision}</dd>
                </>
              )}
            </dl>
            {item.url && (
              <a className={styles.link} href={item.url} target="_blank" rel="noopener noreferrer">
                {t("Open the source")}
              </a>
            )}
          </aside>
        )}
      </div>
      <p className={styles.disclaimer}>{report.disclaimer}</p>
    </div>,
    document.body,
  );
}
