"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { useI18n } from "@/i18n/useI18n";
import { buildGraph, COLUMNS, layout, neighbours, NODE_HEIGHT, NODE_WIDTH, revealDelays } from "./reasoningGraph";
import type { PermitReport } from "./types";
import styles from "./ReasoningGraph.module.css";

/** Text that enters word by word; the words are decoration, so assistive technology reads the sentence once. */
function Reveal({ text, delays }: { text: string; delays: number[] }) {
  return (
    <span aria-label={text} role="text">
      {text.split(" ").map((word, i) => (
        <span key={i} aria-hidden="true" className={styles.word} style={{ animationDelay: `${delays[i]}ms` }}>
          {word}{" "}
        </span>
      ))}
    </span>
  );
}

/** HR-005: how the result was reached, from the same report as the post-its and the PDF. */
export function ReasoningGraph({ report, onClose }: { report: PermitReport; onClose: () => void }) {
  const { t } = useI18n();
  const graph = useMemo(() => buildGraph(report, t), [report, t]);
  const { positions, width, height, columnX } = useMemo(() => layout(graph), [graph]);
  const [selected, setSelected] = useState("conclusion");
  const dialog = useRef<HTMLDivElement>(null);
  const node = graph.nodes.find((n) => n.id === selected) ?? graph.nodes[0];
  const near = neighbours(graph, node.id);
  const delays = revealDelays(node.lines);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") return onClose();
      if (event.key !== "Tab") return;
      // The dialog is modal: Tab cycles inside it and never reaches the page behind.
      const inside = [...(dialog.current?.querySelectorAll<HTMLElement>("button, a[href]") ?? [])];
      const [first, last] = [inside[0], inside[inside.length - 1]];
      const edge = event.shiftKey ? first : last;
      if (document.activeElement === edge || !dialog.current?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus(); // keyboard users return to where they were
    };
  }, [onClose]);

  // In the body: the post-its form their own stacking context, which would leave it under the top bar.
  return createPortal(
    <div ref={dialog} className={styles.overlay} role="dialog" aria-modal="true" aria-label={t("Reasoning graph")}>
      <header className={styles.header}>
        <div>
          <h2 className={styles.title}>{t("How the result was reached")}</h2>
          <p className={styles.subtitle}>
            {t("Each line is a relation stored in this report. It is not a legal determination.")}
          </p>
          {graph.notices.map((notice) => (
            <p key={notice} className={styles.note}>
              {notice}
            </p>
          ))}
        </div>
        <Button variant="secondary" onClick={onClose} autoFocus>
          {t("Close")}
        </Button>
      </header>

      <div className={styles.body}>
        <div className={styles.scroller}>
          <div className={styles.canvas} style={{ width, height }}>
            {COLUMNS.map((name, column) => (
              <p key={name} className={styles.column} style={{ left: columnX(column), width: NODE_WIDTH }}>
                {t(name)}
              </p>
            ))}
            <svg className={styles.edges} width={width} height={height} aria-hidden="true">
              {graph.edges.map((edge, index) => {
                const a = positions.get(edge.from)!;
                const b = positions.get(edge.to)!;
                const [sx, sy, ex, ey] = [a.x + NODE_WIDTH, a.y + NODE_HEIGHT / 2, b.x, b.y + NODE_HEIGHT / 2];
                const mid = (sx + ex) / 2;
                const active = edge.from === node.id || edge.to === node.id;
                const d = `M${sx},${sy} C${mid},${sy} ${mid},${ey} ${ex},${ey}`;
                return (
                  <g key={`${edge.from}-${edge.to}`}>
                    <path
                      className={styles.edge}
                      data-partial={edge.evidenceIds ? true : undefined}
                      data-active={active || undefined}
                      d={d}
                    />
                    {/* The current: it runs along the relation, from source to target. */}
                    <path
                      className={styles.current}
                      data-active={active || undefined}
                      d={d}
                      pathLength={100}
                      style={{ animationDelay: `${-index * 0.7}s` }}
                    />
                  </g>
                );
              })}
            </svg>
            {graph.nodes.map((n) => {
              const { x, y } = positions.get(n.id)!;
              return (
                <button
                  key={n.id}
                  type="button"
                  className={styles.node}
                  data-tone={n.tone}
                  data-near={near.has(n.id) || undefined}
                  aria-pressed={n.id === node.id}
                  style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT, animationDelay: `${n.column * 120}ms` }}
                  onClick={() => setSelected(n.id)}
                >
                  <span className={styles.nodeTitle}>{n.title}</span>
                  <span className={styles.nodeText}>{n.text}</span>
                </button>
              );
            })}
          </div>
        </div>

        <aside key={node.id} className={styles.detail} aria-live="polite">
          <h3 className={styles.detailTitle} aria-label={node.title}>
            {[...node.title].map((letter, i) => (
              <span key={i} aria-hidden="true" className={styles.letter} style={{ animationDelay: `${i * 35}ms` }}>
                {letter}
              </span>
            ))}
          </h3>
          <ul className={styles.lines}>
            {node.lines.map((line, i) => (
              <li key={i}>
                <Reveal text={line} delays={delays[i]} />
              </li>
            ))}
          </ul>
          {node.links.length > 0 && (
            <ul className={styles.links}>
              {node.links.map((l) => (
                <li key={l.url}>
                  <a href={l.url} target="_blank" rel="noopener noreferrer">
                    {l.label}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
      <p className={styles.disclaimer}>{report.disclaimer}</p>
    </div>,
    document.body,
  );
}
