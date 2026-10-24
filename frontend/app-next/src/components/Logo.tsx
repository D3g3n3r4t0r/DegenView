import { useState } from "react";

const DS_CHAIN: Record<string, string> = {
  solana: "solana",
  robinhood: "robinhood",
  base: "base",
  bsc: "bsc",
  ethereum: "ethereum",
  arc: "arc",
  arbitrum: "arbitrum",
  optimism: "optimism",
  polygon: "polygon",
  avalanche: "avalanche",
  monad: "monad",
  zksync: "zksync",
  mantle: "mantle",
  scroll: "scroll",
  blast: "blast",
};

const MARK: Record<string, { d: string; fill?: string; stroke?: string; label: string }> = {
  solana: { d: "M5 16.5h12.5l2-2H7zM5 7.5h12.5l2 2H7zM5 12h12.5l2-2H7", stroke: "#14f195", label: "Solana" },
  robinhood: { d: "M12 3 20 12 12 21 4 12z", stroke: "#c8f169", label: "Robinhood" },
  base: { d: "M8.5 5h7A3.5 3.5 0 0 1 19 8.5v7a3.5 3.5 0 0 1-3.5 3.5h-7A3.5 3.5 0 0 1 5 15.5v-7A3.5 3.5 0 0 1 8.5 5z", fill: "#3c8aff", label: "Base" },
  bsc: { d: "M12 3.5 15 6.5 12 9.5 9 6.5zM12 14.5l3 3-3 3-3-3zM6.5 9l3 3-3 3-3-3zM17.5 9l3 3-3 3-3-3zM12 9.5l2.5 2.5-2.5 2.5L9.5 12z", fill: "#f0b90b", label: "BNB Chain" },
  ethereum: { d: "M12 2.5 6 12.2 12 16l6-3.8zM6 13.6l6 8 6-8-6 3.8z", fill: "#a5b4fc", label: "Ethereum" },
  arc: { d: "M4 19a8 8 0 0 1 16 0h-3.5a4.5 4.5 0 0 0-9 0z", stroke: "currentColor", label: "Arc" },
  layer: { d: "M12 3 3 8l9 5 9-5-9-5zM3 12.5l9 5 9-5M3 17l9 4 9-4", stroke: "#38bdf8", label: "Layer (L0 / L1 / L2)" },
  arbitrum: { d: "M12 3 4 7.5v9L12 21l8-4.5v-9L12 3zm-2 6 4 7M14 9l-4 7", stroke: "#28a0f0", label: "Arbitrum" },
  optimism: { d: "M8.5 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM14 15.5v-7h2.5a2.2 2.2 0 0 1 0 4.4H14", stroke: "#ff0420", label: "Optimism" },
  polygon: { d: "M8 7.5 4.5 9.5v4L8 15.5l3.5-2v-4L8 7.5zm8 1 3.5 2v4L16 16.5l-3.5-2v-4l3.5-2z", stroke: "#8247e5", label: "Polygon" },
  avalanche: { d: "M12 4 4.5 19h5l2.5-5 2.5 5h5L12 4z", fill: "#e84142", label: "Avalanche" },
  monad: { d: "M12 3.5 20.5 12 12 20.5 3.5 12 12 3.5zm0 4.5L8 12l4 4 4-4-4-4z", stroke: "#836ef9", label: "Monad" },
  zksync: { d: "M4 12 10 7v3.5h5L10 14h4v3l-10-5zm16 0-6 5v-3.5H9l5-3.5h-4V7l10 5z", fill: "#4e529a", label: "zkSync" },
  mantle: { d: "M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9zm-3 6 3 3 3-3v6h-6V9z", stroke: "#65b3ae", label: "Mantle" },
};

/** The token picture, or a rounded square with its initial (direction A). */
export function Tile({ symbol, image, chain, token, className = "" }: { symbol?: string; image?: string; chain?: string; token?: string; className?: string }) {
  const [broken, setBroken] = useState(false);
  const seed = String(token || symbol || "?");
  const h = [...seed].reduce((a, c) => (a * 33 + c.charCodeAt(0)) >>> 0, 5381);
  const addr = token && token.startsWith("0x") ? token.toLowerCase() : token;
  const chainKey = chain ? chain.toLowerCase() : "";
  const src = image || (addr && chainKey && DS_CHAIN[chainKey] ? `https://dd.dexscreener.com/ds-data/tokens/${DS_CHAIN[chainKey]}/${addr}.png` : "");
  const style = { "--h1": h % 360, "--h2": (h >> 9) % 360, "--rot": `${(h >> 5) % 360}deg` } as React.CSSProperties;
  return (
    <span className={`tile ${className}`} style={style} data-shape={(h >> 3) % 4}>
      <b className="letter" aria-hidden="true">{String(symbol || "?").replace(/^\$/, "").charAt(0).toUpperCase()}</b>
      {src && !broken && <img src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setBroken(true)} />}
    </span>
  );
}

export function Logo({ size = 52, ...t }: { size?: number; symbol?: string; image?: string; chain?: string; token?: string }) {
  const chainKey = t.chain ? t.chain.toLowerCase() : "";
  const m = chainKey ? MARK[chainKey] : undefined;
  const badgeCls =
    size < 28
      ? "absolute -bottom-0.5 -right-0.5 grid h-3.5 w-3.5 place-items-center rounded-full bg-pill not-italic shadow-[0_0_0_1.5px_var(--c-bg)]"
      : size < 44
        ? "absolute -bottom-0.5 -right-0.5 grid h-[17px] w-[17px] place-items-center rounded-full bg-pill not-italic shadow-[0_0_0_1.75px_var(--c-bg)]"
        : "absolute -bottom-1 -right-1 grid h-5 w-5 place-items-center rounded-full bg-pill not-italic shadow-[0_0_0_2px_var(--c-bg)]";
  const svgCls = size < 28 ? "h-[9px] w-[9px]" : size < 44 ? "h-[11px] w-[11px]" : "h-[13px] w-[13px]";
  return (
    <span className="relative block flex-none" style={{ width: size, height: size }}>
      <Tile {...t} />
      {m && (
        <i className={badgeCls} title={m.label}>
          <svg viewBox="0 0 24 24" className={svgCls} aria-hidden="true" fill={m.fill ?? "none"} stroke={m.stroke ?? "none"} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"><path d={m.d} /></svg>
        </i>
      )}
    </span>
  );
}
