import { useState } from "react";

// "Scan a token": the pill field with the round button inside, as in the current app.
export function ScanField({ onScan, autoFocus }: { onScan: (q: string) => void; autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  return (
    <form className="relative mt-3" onSubmit={(ev) => { ev.preventDefault(); if (q.trim()) onScan(q.trim()); }}>
      <input value={q} onChange={(ev) => setQ(ev.target.value)} autoFocus={autoFocus} placeholder="Scan a token: ticker or address"
        className="h-12 w-full rounded-full border border-line bg-bg pl-5 pr-14 text-[16px] outline-none placeholder:text-ink-3 focus:border-ink-3" />
      <button aria-label="Scan" className="absolute right-1 top-1 grid h-10 w-10 place-items-center rounded-full bg-ink text-on-ink">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
      </button>
    </form>
  );
}
