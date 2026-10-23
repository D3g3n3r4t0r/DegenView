import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { useDesk } from "../lib/desk";

/** A bottom sheet (sheets.js): title, a line under it, any body; drag down, tap outside or Escape to close. */
export function Sheet({ open, title, sub, onClose, children }: {
  open: boolean; title?: string; sub?: string; onClose: () => void; children: React.ReactNode;
}) {
  // On a computer the sheet is a panel on the right, not a drawer from the bottom.
  const desk = useDesk();
  useEffect(() => {
    if (!open) return;
    const k = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/35" onClick={onClose}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.section role="dialog" aria-modal="true" aria-label={title}
            className="fixed inset-x-0 bottom-0 z-50 mx-auto max-h-[88vh] max-w-xl overflow-y-auto rounded-t-[28px] bg-card px-5 pb-[max(24px,env(safe-area-inset-bottom))] pt-3 desk:inset-x-auto desk:bottom-3.5 desk:right-3.5 desk:top-3.5 desk:max-h-none desk:w-[460px] desk:rounded-[28px] desk:px-7 desk:pt-7 desk:shadow-float"
            initial={desk ? { x: "110%" } : { y: "100%" }} animate={desk ? { x: 0 } : { y: 0 }} exit={desk ? { x: "110%" } : { y: "100%" }} transition={{ type: "spring", stiffness: 400, damping: 40 }}
            drag={desk ? false : "y"} dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, i) => { if (i.offset.y > 110 || i.velocity.y > 650) onClose(); }}>
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-text-4 desk:hidden" />
            {title && <h2 className="text-[20px] font-semibold">{title}</h2>}
            {sub && <p className="mt-1 text-[14px] text-text-2">{sub}</p>}
            <div className="mt-4">{children}</div>
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}
