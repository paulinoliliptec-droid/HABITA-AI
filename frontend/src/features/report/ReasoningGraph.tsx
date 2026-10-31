"use client";

import { useId, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useI18n } from "@/i18n/useI18n";
import { buildGraph, COLUMNS, nodeIcon, edgeKey, flowOf, layout, NODE_HEIGHT, NODE_WIDTH, revealDelays } from "./reasoningGraph";
import type { PermitReport } from "./types";
import { useModal } from "./useModal";
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
  const sparkId = useId().replaceAll(":", "");
  const node = graph.nodes.find((n) => n.id === selected) ?? graph.nodes[0];
  const flow = useMemo(() => flowOf(graph, node.id), [graph, node.id]);
  const flowNodes = graph.nodes.filter((n) => flow.nodes.has(n.id) && n.id !== node.id);
  const delays = revealDelays(node.lines);

  useModal(dialog, onClose);

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
              <defs>
                {/* Bends the selected node's lines like an arc; a change of shape, slow, never a flash. */}
                <filter id={sparkId} x="-10%" y="-40%" width="120%" height="180%">
                  <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="3" result="noise">
                    <animate attributeName="seed" values="3;9;17;26;3" dur="2.4s" calcMode="discrete" repeatCount="indefinite" />
                  </feTurbulence>
                  <feDisplacementMap in="SourceGraphic" in2="noise" scale="7" />
                </filter>
              </defs>
              {graph.edges.map((edge, index) => {
                const a = positions.get(edge.from)!;
                const b = positions.get(edge.to)!;
                const [sx, sy, ex, ey] = [a.x + NODE_WIDTH, a.y + NODE_HEIGHT / 2, b.x, b.y + NODE_HEIGHT / 2];
                const mid = (sx + ex) / 2;
                const active = flow.edges.has(edgeKey(edge));
                const d = `M${sx},${sy} C${mid},${sy} ${mid},${ey} ${ex},${ey}`;
                return (
                  <g key={edgeKey(edge)} className={styles.synapse} data-out={active ? undefined : true}>
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
                      data-partial={edge.evidenceIds ? true : undefined}
                      d={d}
                      pathLength={100}
                      style={{ animationDelay: `${-index * 0.7}s` }}
                    />
                    {active && (
                      <path
                        className={styles.arc}
                        data-partial={edge.evidenceIds ? true : undefined}
                        d={d}
                        filter={`url(#${sparkId})`}
                      />
                    )}
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
                  data-flow={flow.nodes.has(n.id) || undefined}
                  data-out={flow.nodes.has(n.id) ? undefined : true}
                  aria-pressed={n.id === node.id}
                  style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT, "--column": n.column } as CSSProperties}
                  onClick={() => setSelected(n.id)}
                >
                  <span className={styles.soma} aria-hidden="true" />
                  <span className={styles.nodeTitle}>
                    <Icon name={nodeIcon(n.id)} size={16} className={styles.nodeIcon} />
                    {n.title}
                  </span>
                  <span className={styles.nodeText}>{n.text}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* The live region stays; only its content changes, so screen readers announce each selection. */}
        <aside className={styles.detail} aria-live="polite">
          <div key={node.id} className={styles.detailContent}>
            <Icon name={nodeIcon(node.id)} size={28} className={styles.detailIcon} />
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
            {flowNodes.length > 0 && (
              <nav className={styles.flow} aria-label={t("Blocks in this flow")}>
                <h4 className={styles.flowTitle}>{t("Blocks in this flow")}</h4>
                <ul className={styles.flowList}>
                  {flowNodes.map((n) => (
                    <li key={n.id}>
                      <button type="button" className={styles.flowItem} data-tone={n.tone} onClick={() => setSelected(n.id)}>
                        {n.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
            )}
          </div>
        </aside>
      </div>
      <p className={styles.disclaimer}>{report.disclaimer}</p>
    </div>,
    document.body,
  );
}
