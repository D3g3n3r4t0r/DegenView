import { useState } from "react";

export function TokenLogo({ src, symbol, size = 52 }: { src?: string; symbol: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const style = { width: size, height: size };
  if (src && !broken) return <img src={src} alt="" style={style} className="shrink-0 rounded-[14px] bg-pill object-cover" onError={() => setBroken(true)} />;
  return <div style={style} className="grid shrink-0 place-items-center rounded-[14px] bg-pill text-[13px] font-semibold text-ink-2">{symbol.slice(0, 2)}</div>;
}
