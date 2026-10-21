import { useState } from "react";

export function TokenLogo({ src, symbol, size = 36 }: { src?: string; symbol: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const style = { width: size, height: size };
  if (src && !broken) return <img src={src} alt="" style={style} className="shrink-0 rounded-full bg-raised object-cover" onError={() => setBroken(true)} />;
  const hue = [...symbol].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) % 360, 7);
  return (
    <div style={{ ...style, background: `oklch(42% 0.12 ${hue})` }} className="grid shrink-0 place-items-center rounded-full text-[12px] font-semibold">
      {symbol.slice(0, 2)}
    </div>
  );
}
