import Link from "next/link";
import styles from "./TopBar.module.css";

// Only modules that actually exist are listed. Permit and Afford join when they ship.
const MODULES = [{ label: "Property", href: "/" }] as const;

export function TopBar() {
  return (
    <header className={styles.topbar}>
      <Link href="/" className={styles.identity} aria-label="HABITA AI, home">
        <span className={styles.wordmark}>
          HABITA<span className={styles.ai}>AI</span>
        </span>
        <span className={styles.divider} aria-hidden="true" />
        <span className={styles.subtitle}>Global Property Intelligence &amp; Permitting OS</span>
      </Link>

      <nav aria-label="Modules" className={styles.nav}>
        {MODULES.map((module) => (
          <Link key={module.href} href={module.href} className={styles.navItem} aria-current="page">
            {module.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
