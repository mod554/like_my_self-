"use client";

// Compteur animé (count-up) — Framer Motion, respecte prefers-reduced-motion.
// Présentation pure : reçoit la valeur déjà calculée côté serveur et reproduit
// exactement le format d'affichage existant (aucun changement de logique).

import { useEffect, useRef } from "react";
import { animate, useInView, useReducedMotion } from "framer-motion";

interface Props {
  value: number;
  devise?: string;
  durationMs?: number;
}

function formatPrix(v: number, devise?: string): string {
  const f = v >= 1000
    ? v.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
    : v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return devise ? `${f} ${devise}` : f;
}

export default function CountUp({ value, devise, durationMs = 1100 }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced || !inView) {
      el.textContent = formatPrix(value, devise);
      return;
    }
    const controls = animate(0, value, {
      duration: durationMs / 1000,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => { el.textContent = formatPrix(v, devise); },
      onComplete: () => { el.textContent = formatPrix(value, devise); },
    });
    return () => controls.stop();
  }, [value, devise, durationMs, inView, reduced]);

  // Rendu serveur : valeur finale directement (SEO + no-JS + reduced motion)
  return <span ref={ref}>{formatPrix(value, devise)}</span>;
}
