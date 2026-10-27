import type { CSSProperties } from "react";
import styles from "./Skeleton.module.css";

export function Skeleton({ width = "100%", height = "1em", style }: { width?: string; height?: string; style?: CSSProperties }) {
  return <span className={styles.skeleton} style={{ width, height, ...style }} aria-hidden="true" />;
}
