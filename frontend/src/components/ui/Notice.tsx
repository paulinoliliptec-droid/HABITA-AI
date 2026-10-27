import type { ReactNode } from "react";
import { Icon } from "./Icon";
import styles from "./Notice.module.css";

type Tone = "neutral" | "warning" | "danger";

const ICONS = { neutral: "info", warning: "alert", danger: "alert" } as const;

export function Notice({
  tone = "neutral",
  title,
  children,
  action,
  live = false,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
  /** Announce to screen readers when it appears. */
  live?: boolean;
}) {
  return (
    <div className={`${styles.notice} ${styles[tone]}`} role={live ? (tone === "danger" ? "alert" : "status") : undefined}>
      <Icon name={ICONS[tone]} size={18} className={styles.icon} />
      <div className={styles.body}>
        {title && <p className={styles.title}>{title}</p>}
        {children && <div className={styles.text}>{children}</div>}
        {action && <div className={styles.action}>{action}</div>}
      </div>
    </div>
  );
}
