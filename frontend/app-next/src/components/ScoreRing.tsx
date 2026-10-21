import { motion } from "motion/react";

// The score as a ring that fills on first draw (stroke offset, GPU-cheap).
export function ScoreRing({ score, size = 38 }: { score: number; size?: number }) {
  const r = size / 2 - 3, c = 2 * Math.PI * r;
  const color = score >= 85 ? "var(--color-up)" : score >= 70 ? "var(--color-amber)" : "var(--color-ink-dim)";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={3} />
        <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={3} strokeLinecap="round"
          strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - score / 100) }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }} />
      </svg>
      <span className="num absolute inset-0 grid place-items-center text-[11px] font-medium">{Math.round(score)}</span>
    </div>
  );
}
