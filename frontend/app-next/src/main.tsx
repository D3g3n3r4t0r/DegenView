import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { useLang } from "./lib/i18n";
import "./index.css";

// `npm run dev` with ?mock: fake data for screenshots (never in the build).
if (import.meta.env.DEV && /[?&]mock/.test(location.search)) await import("./mock");

// A new language redraws the whole app: texts built once (labels, lists) read it again.
function Root() { return <App key={useLang()} />; }

createRoot(document.getElementById("root")!).render(<StrictMode><Root /></StrictMode>);
