import { useEffect, useRef } from "react";
import { animate, useInView, useReducedMotion } from "motion/react";

// RareUI "Animated counter", reduced to one text node: the value counts up
// when it first scrolls into view and eases to each new value after that.
export function AnimatedNumber({ value, format, duration = 0.9 }: {
  value: number; format: (v: number) => string; duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const from = useRef(0);
  const seen = useInView(ref, { once: true });
  const still = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || !seen) return;
    if (still) { el.textContent = format(value); from.current = value; return; }
    const ctl = animate(from.current, value, {
      duration, ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => { el.textContent = format(v); },
    });
    from.current = value;
    return () => ctl.stop();
  }, [value, seen, still, format, duration]);

  return <span ref={ref} className="num">{format(still ? value : 0)}</span>;
}
