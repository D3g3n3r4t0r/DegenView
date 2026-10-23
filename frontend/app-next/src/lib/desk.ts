import { useSyncExternalStore } from "react";

// The desktop layout (sidebar, columns, the token page beside the list) from
// this width up; the same width index.html used to send to the old app.
export const DESK = "(min-width: 1100px)";
const mq = matchMedia(DESK);
export const isDesk = () => mq.matches;
export const useDesk = () => useSyncExternalStore((f) => { mq.addEventListener("change", f); return () => mq.removeEventListener("change", f); }, isDesk);
