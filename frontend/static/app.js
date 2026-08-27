(() => {
  "use strict";

  // Millimetrata Blueprint palette — every mark on the chart stays a tonal
  // variation of ink/accent/stamp/bull/bear, no arbitrary bright hues.
  const COLORS = {
    paperBg: "#f2ede1",
    ink: "#26312e",
    inkDim: "#5c675f",
    gridMinor: "rgba(168, 184, 174, 0.45)",
    gridMajor: "rgba(127, 148, 136, 0.55)",
    bull: "#1f7a44",
    bear: "#8c2f1f",
    accent: "#1f4e6b",
    stamp: "#8a6d3b",
    bullFill: "rgba(31, 122, 68, 0.16)",
    bullBorder: "rgba(31, 122, 68, 0.9)",
    bearFill: "rgba(140, 47, 31, 0.14)",
    bearBorder: "rgba(140, 47, 31, 0.85)",
    confluenceFill: "rgba(138, 109, 59, 0.16)",
    confluenceBorder: "rgba(138, 109, 59, 0.85)",
    ema20: "#1f4e6b",
    ema50: "#8a6d3b",
    bb: "#7f9488",
    vwap: "#5c675f",
    rsi: "#1f4e6b",
    macd: "#1f4e6b",
    macdSignal: "#8a6d3b",
  };

  const TF_LABELS = { htf: "HTF", mtf: "MTF", ltf: "LTF" };
  const CANONICAL_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "2d", "3d", "5d", "1w", "1M"];
  const DEFAULT_INTERVALS = { htf: "1d", mtf: "1h", ltf: "15m" };
  const DEFAULT_PRIMARY_INTERVAL = "15m";

  // One dropdown is all the user picks — HTF/MTF for the multi-timeframe SMC
  // confluence engine are derived automatically from it (two and four steps
  // up the canonical ladder), instead of three interval pickers that could
  // drift out of sync with each other.
  const PRIMARY_TO_TRIAD = {
    "1m": { ltf: "1m", mtf: "15m", htf: "4h" },
    "5m": { ltf: "5m", mtf: "1h", htf: "1d" },
    "15m": { ltf: "15m", mtf: "1h", htf: "1d" },
    "30m": { ltf: "30m", mtf: "4h", htf: "1d" },
    "1h": { ltf: "1h", mtf: "4h", htf: "1w" },
    "4h": { ltf: "4h", mtf: "1d", htf: "1w" },
    "1d": { ltf: "1d", mtf: "1w", htf: "1M" },
    "2d": { ltf: "2d", mtf: "1w", htf: "1M" },
    "3d": { ltf: "3d", mtf: "1w", htf: "1M" },
    "5d": { ltf: "5d", mtf: "1M", htf: "1M" },
    "1w": { ltf: "1w", mtf: "1M", htf: "1M" },
    "1M": { ltf: "1M", mtf: "1M", htf: "1M" },
  };

  // ---- Series Primitive: filled rectangle between two (time, price) points ----
  function positionsBox(pos1, pos2, pixelRatio) {
    const a = Math.round(pixelRatio * pos1);
    const b = Math.round(pixelRatio * pos2);
    return { position: Math.min(a, b), length: Math.abs(b - a) + 1 };
  }

  class RectangleRenderer {
    constructor(p1, p2, fillColor, borderColor) {
      this._p1 = p1;
      this._p2 = p2;
      this._fillColor = fillColor;
      this._borderColor = borderColor;
    }
    draw(target) {
      target.useBitmapCoordinateSpace((scope) => {
        if (this._p1.x === null || this._p1.y === null || this._p2.x === null || this._p2.y === null) return;
        const ctx = scope.context;
        const h = positionsBox(this._p1.x, this._p2.x, scope.horizontalPixelRatio);
        const v = positionsBox(this._p1.y, this._p2.y, scope.verticalPixelRatio);
        ctx.fillStyle = this._fillColor;
        ctx.fillRect(h.position, v.position, h.length, v.length);
        ctx.strokeStyle = this._borderColor;
        ctx.lineWidth = 1;
        ctx.strokeRect(h.position, v.position, h.length, v.length);
      });
    }
  }

  class RectanglePaneView {
    constructor(source) {
      this._source = source;
      this._p1 = { x: null, y: null };
      this._p2 = { x: null, y: null };
    }
    update() {
      const { chart, series, point1, point2 } = this._source;
      if (!chart || !series) return;
      const y1 = series.priceToCoordinate(point1.price);
      const y2 = series.priceToCoordinate(point2.price);
      const timeScale = chart.timeScale();
      const x1 = timeScale.timeToCoordinate(point1.time);
      const x2 = timeScale.timeToCoordinate(point2.time);
      this._p1 = { x: x1, y: y1 };
      this._p2 = { x: x2, y: y2 };
    }
    renderer() {
      return new RectangleRenderer(this._p1, this._p2, this._source.fillColor, this._source.borderColor);
    }
    zOrder() {
      return "normal";
    }
  }

  class RectanglePrimitive {
    constructor(point1, point2, fillColor, borderColor) {
      this.point1 = point1;
      this.point2 = point2;
      this.fillColor = fillColor;
      this.borderColor = borderColor;
      this.chart = null;
      this.series = null;
      this._paneViews = [new RectanglePaneView(this)];
    }
    attached({ chart, series }) {
      this.chart = chart;
      this.series = series;
    }
    detached() {
      this.chart = null;
      this.series = null;
    }
    updateAllViews() {
      this._paneViews.forEach((v) => v.update());
    }
    paneViews() {
      return this._paneViews;
    }
  }

  // ---- Series Primitive: freehand line between two (time, price) points,
  // optionally with an arrowhead at the second point (reused for both the
  // Trend Line and Arrow drawing tools) ----
  class LineRenderer {
    constructor(p1, p2, color, width, arrow) {
      this._p1 = p1;
      this._p2 = p2;
      this._color = color;
      this._width = width;
      this._arrow = arrow;
    }
    draw(target) {
      target.useBitmapCoordinateSpace((scope) => {
        if (this._p1.x === null || this._p1.y === null || this._p2.x === null || this._p2.y === null) return;
        const ctx = scope.context;
        const x1 = this._p1.x * scope.horizontalPixelRatio;
        const y1 = this._p1.y * scope.verticalPixelRatio;
        const x2 = this._p2.x * scope.horizontalPixelRatio;
        const y2 = this._p2.y * scope.verticalPixelRatio;
        ctx.strokeStyle = this._color;
        ctx.lineWidth = this._width * scope.horizontalPixelRatio;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        if (this._arrow) {
          const angle = Math.atan2(y2 - y1, x2 - x1);
          const headLen = 9 * scope.horizontalPixelRatio;
          ctx.beginPath();
          ctx.moveTo(x2, y2);
          ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
          ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
          ctx.closePath();
          ctx.fillStyle = this._color;
          ctx.fill();
        }
      });
    }
  }

  class LinePaneView {
    constructor(source) {
      this._source = source;
      this._p1 = { x: null, y: null };
      this._p2 = { x: null, y: null };
    }
    update() {
      const { chart, series, point1, point2 } = this._source;
      if (!chart || !series) return;
      this._p1 = { x: chart.timeScale().timeToCoordinate(point1.time), y: series.priceToCoordinate(point1.price) };
      this._p2 = { x: chart.timeScale().timeToCoordinate(point2.time), y: series.priceToCoordinate(point2.price) };
    }
    renderer() {
      return new LineRenderer(this._p1, this._p2, this._source.color, this._source.width, this._source.arrow);
    }
    zOrder() {
      return "normal";
    }
  }

  class LinePrimitive {
    constructor(point1, point2, color, width, arrow) {
      this.point1 = point1;
      this.point2 = point2;
      this.color = color;
      this.width = width;
      this.arrow = arrow;
      this.chart = null;
      this.series = null;
      this._paneViews = [new LinePaneView(this)];
    }
    attached({ chart, series }) {
      this.chart = chart;
      this.series = series;
    }
    detached() {
      this.chart = null;
      this.series = null;
    }
    updateAllViews() {
      this._paneViews.forEach((v) => v.update());
    }
    paneViews() {
      return this._paneViews;
    }
  }

  // ---- Series Primitive: a text label anchored to one (time, price) point ----
  class TextRenderer {
    constructor(p, text, color) {
      this._p = p;
      this._text = text;
      this._color = color;
    }
    draw(target) {
      target.useBitmapCoordinateSpace((scope) => {
        if (this._p.x === null || this._p.y === null || !this._text) return;
        const ctx = scope.context;
        ctx.font = `${11 * scope.verticalPixelRatio}px "Space Mono", monospace`;
        ctx.fillStyle = this._color;
        ctx.textBaseline = "bottom";
        ctx.fillText(this._text, this._p.x * scope.horizontalPixelRatio + 5, this._p.y * scope.verticalPixelRatio - 5);
      });
    }
  }

  class TextPaneView {
    constructor(source) {
      this._source = source;
      this._p = { x: null, y: null };
    }
    update() {
      const { chart, series, point } = this._source;
      if (!chart || !series) return;
      this._p = { x: chart.timeScale().timeToCoordinate(point.time), y: series.priceToCoordinate(point.price) };
    }
    renderer() {
      return new TextRenderer(this._p, this._source.text, this._source.color);
    }
    zOrder() {
      return "normal";
    }
  }

  class TextPrimitive {
    constructor(point, text, color) {
      this.point = point;
      this.text = text;
      this.color = color;
      this.chart = null;
      this.series = null;
      this._paneViews = [new TextPaneView(this)];
    }
    attached({ chart, series }) {
      this.chart = chart;
      this.series = series;
    }
    detached() {
      this.chart = null;
      this.series = null;
    }
    updateAllViews() {
      this._paneViews.forEach((v) => v.update());
    }
    paneViews() {
      return this._paneViews;
    }
  }

  // ---- Series Primitive: Fibonacci retracement — horizontal levels spanning
  // the two anchor points, each labeled with its ratio and price ----
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

  class FibRenderer {
    constructor(x1, x2, levels, color) {
      this._x1 = x1;
      this._x2 = x2;
      this._levels = levels; // [{ y, label }]
      this._color = color;
    }
    draw(target) {
      target.useBitmapCoordinateSpace((scope) => {
        if (this._x1 === null || this._x2 === null) return;
        const ctx = scope.context;
        const xa = Math.min(this._x1, this._x2) * scope.horizontalPixelRatio;
        const xb = Math.max(this._x1, this._x2) * scope.horizontalPixelRatio;
        ctx.lineWidth = Math.max(1, scope.verticalPixelRatio);
        ctx.font = `${10 * scope.verticalPixelRatio}px "Space Mono", monospace`;
        this._levels.forEach(({ y, label }) => {
          if (y === null) return;
          const yy = y * scope.verticalPixelRatio;
          ctx.strokeStyle = this._color;
          ctx.beginPath();
          ctx.moveTo(xa, yy);
          ctx.lineTo(xb, yy);
          ctx.stroke();
          ctx.fillStyle = this._color;
          ctx.fillText(label, xb + 4, yy + 4);
        });
      });
    }
  }

  class FibPaneView {
    constructor(source) {
      this._source = source;
      this._x1 = null;
      this._x2 = null;
      this._levels = [];
    }
    update() {
      const { chart, series, point1, point2 } = this._source;
      if (!chart || !series) return;
      this._x1 = chart.timeScale().timeToCoordinate(point1.time);
      this._x2 = chart.timeScale().timeToCoordinate(point2.time);
      this._levels = FIB_LEVELS.map((ratio) => {
        const price = point1.price + ratio * (point2.price - point1.price);
        return { y: series.priceToCoordinate(price), label: `${(ratio * 100).toFixed(1)}% (${price.toFixed(2)})` };
      });
    }
    renderer() {
      return new FibRenderer(this._x1, this._x2, this._levels, this._source.color);
    }
    zOrder() {
      return "normal";
    }
  }

  class FibPrimitive {
    constructor(point1, point2, color) {
      this.point1 = point1;
      this.point2 = point2;
      this.color = color;
      this.chart = null;
      this.series = null;
      this._paneViews = [new FibPaneView(this)];
    }
    attached({ chart, series }) {
      this.chart = chart;
      this.series = series;
    }
    detached() {
      this.chart = null;
      this.series = null;
    }
    updateAllViews() {
      this._paneViews.forEach((v) => v.update());
    }
    paneViews() {
      return this._paneViews;
    }
  }

  // ---- App state ----
  const state = {
    assetType: "stock",
    cryptoExchange: "mexc", // set automatically from the picked search suggestion
    // Always "ltf" now — the single timeframe dropdown *is* the chart's
    // timeframe; MTF/HTF exist only for the derived confluence context.
    activeTimeframe: "ltf",
    data: null,
    suggestions: [],
    activeSuggestionIndex: -1,
    liveSocket: null,
    liveRefreshTimer: null,
    seenAlertKeys: new Set(),
    alertsSeeded: false,
    watchlistAssetType: "stock",
    pineScripts: [],
    activePineScriptId: null,
    activePineParams: [],
    activePineIsStrategy: true,
    pineActive: false,
    pineLastResult: null,
    availableStrategies: [],
    logScale: false,
    // Kept minimal by default — every structure/liquidity level draws its own
    // chart label, and turning them all on at once buries the price action
    // (especially on narrow screens). Confluence zones stay on since they're
    // already a synthesized, filtered view rather than raw noise.
    layers: {
      order_block: false,
      fvg: false,
      liquidity: false,
      structure: false,
      confluence: true,
      ema: true,
      bbands: false,
      vwap: false,
      rsi: false,
      macd: false,
      stoch: false,
    },
  };

  const overlays = {
    lineSeries: [],
    priceLines: [],
    primitives: [],
    hitZones: [], // {price_low, price_high, start_time, end_time, label}
  };

  let mainChart, candleSeries, rsiChart, rsiSeries, macdChart, macdLineSeries, macdSignalSeries, macdHistSeries;
  let stochChart, stochKSeries, stochDSeries;
  let equityChart, equitySeries;

  const el = (id) => document.getElementById(id);
  const tooltipEl = el("tooltip");

  // Chart containers start hidden (display:none) until the first search
  // succeeds, so the library's built-in autoSize can miss the 0 -> real
  // size transition. A manual ResizeObserver per container is more robust.
  function observeResize(container, chart) {
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) chart.resize(width, height);
    });
    ro.observe(container);
  }

  function resizeAllCharts() {
    [
      [el("main-chart"), mainChart],
      [el("rsi-chart"), rsiChart],
      [el("macd-chart"), macdChart],
      [el("stoch-chart"), stochChart],
      [el("equity-chart"), equityChart],
    ].forEach(([container, chart]) => {
      if (container.clientWidth > 0 && container.clientHeight > 0) {
        chart.resize(container.clientWidth, container.clientHeight);
      }
    });
  }

  function populateIntervalSelects() {
    const select = el("interval-primary");
    CANONICAL_INTERVALS.forEach((iv) => {
      const opt = document.createElement("option");
      opt.value = iv;
      opt.textContent = iv;
      if (iv === DEFAULT_PRIMARY_INTERVAL) opt.selected = true;
      select.appendChild(opt);
    });

    const wlSelect = el("watchlist-interval");
    CANONICAL_INTERVALS.forEach((iv) => {
      const opt = document.createElement("option");
      opt.value = iv;
      opt.textContent = iv;
      if (iv === "1d") opt.selected = true;
      wlSelect.appendChild(opt);
    });
  }

  async function populateStrategySelects() {
    let strategies = [];
    try {
      const resp = await fetch("/api/strategies");
      if (resp.ok) strategies = await resp.json();
    } catch (err) {
      strategies = [];
    }
    state.availableStrategies = strategies;
    const select = el("active-strategy-select");
    select.innerHTML = "";
    strategies.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
  }

  // Each ticker is a card that expands to show one on/off toggle per
  // available strategy — a ticker can have several strategies watched at
  // once (previously one strategy meant one whole separate watchlist row).
  async function loadWatchlist() {
    let entries = [];
    try {
      const resp = await fetch("/api/watchlist");
      if (resp.ok) entries = await resp.json();
    } catch (err) {
      entries = [];
    }
    const list = el("watchlist-list");
    const openIds = new Set(
      Array.from(list.querySelectorAll(".tick-card.open")).map((c) => c.dataset.entryId)
    );
    list.innerHTML = "";
    if (!entries.length) {
      const li = document.createElement("li");
      li.className = "panel-hint";
      li.textContent = "Nessun ticker in watchlist.";
      list.appendChild(li);
      return;
    }
    entries.forEach((entry) => {
      const card = document.createElement("li");
      card.className = "tick-card" + (openIds.has(entry.id) ? " open" : "");
      card.dataset.entryId = entry.id;

      const head = document.createElement("div");
      head.className = "tick-card-head";
      const activeCount = entry.strategies.length;
      head.innerHTML = `
        <span><span class="wl-symbol">${entry.symbol}</span><span class="wl-exch">${entry.asset_type === "crypto" ? entry.exchange.toUpperCase() : "Azioni"} · ${entry.interval}</span></span>
        <span class="wl-summary">${activeCount ? `${activeCount} attiv${activeCount === 1 ? "a" : "e"}` : "nessuna attiva"}</span>
        <span class="wl-caret">▾</span>
      `;
      head.addEventListener("click", (e) => {
        if (e.target.closest(".wl-remove")) return;
        card.classList.toggle("open");
      });

      const body = document.createElement("div");
      body.className = "tick-card-body";

      const intervalRow = document.createElement("div");
      intervalRow.className = "strat-row wl-interval-row";
      const intervalLabel = document.createElement("span");
      intervalLabel.textContent = "Timeframe strategie";
      const intervalSelect = document.createElement("select");
      intervalSelect.className = "wl-interval-select";
      CANONICAL_INTERVALS.forEach((iv) => {
        const opt = document.createElement("option");
        opt.value = iv;
        opt.textContent = iv;
        if (iv === entry.interval) opt.selected = true;
        intervalSelect.appendChild(opt);
      });
      intervalSelect.addEventListener("click", (e) => e.stopPropagation());
      intervalSelect.addEventListener("change", async () => {
        try {
          await fetch(`/api/watchlist/${entry.id}/interval`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ interval: intervalSelect.value }),
          });
        } finally {
          loadWatchlist();
        }
      });
      intervalRow.appendChild(intervalLabel);
      intervalRow.appendChild(intervalSelect);
      body.appendChild(intervalRow);

      state.availableStrategies.forEach((name) => {
        const isOn = entry.strategies.includes(name);
        const row = document.createElement("div");
        row.className = "strat-row";
        const label = document.createElement("span");
        label.textContent = name;
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "wl-toggle" + (isOn ? " on" : "");
        toggle.innerHTML = '<span class="knob"></span>';
        toggle.addEventListener("click", async () => {
          const nextOn = !toggle.classList.contains("on");
          toggle.classList.toggle("on", nextOn);
          try {
            await fetch(`/api/watchlist/${entry.id}/strategy`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ strategy_name: name, enabled: nextOn }),
            });
          } finally {
            loadWatchlist();
          }
        });
        row.appendChild(label);
        row.appendChild(toggle);
        body.appendChild(row);
      });

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "wl-remove";
      removeBtn.textContent = "✕ Rimuovi ticker";
      removeBtn.style.marginTop = "4px";
      removeBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`/api/watchlist/${entry.id}`, { method: "DELETE" });
        loadWatchlist();
      });
      body.appendChild(removeBtn);

      card.appendChild(head);
      card.appendChild(body);
      list.appendChild(card);
    });
  }

  function getSelectedIntervals() {
    return PRIMARY_TO_TRIAD[el("interval-primary").value];
  }

  function initCharts() {
    // TradingView's own mobile app keeps chart gridlines barely-there —
    // dense gridlines that read as "considered" on a wide desktop screen
    // just look busy/dated on a phone. Same hue, much lower opacity.
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    const chartGridColor = isMobile ? "rgba(168, 184, 174, 0.18)" : COLORS.gridMinor;
    const baseOptions = {
      layout: { background: { color: COLORS.paperBg }, textColor: COLORS.inkDim, fontFamily: "'Space Mono', monospace" },
      grid: { vertLines: { color: chartGridColor }, horzLines: { color: chartGridColor } },
      rightPriceScale: { borderColor: COLORS.gridMajor },
      timeScale: { borderColor: COLORS.gridMajor, timeVisible: true, secondsVisible: false },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: COLORS.inkDim, labelBackgroundColor: COLORS.ink },
        horzLine: { color: COLORS.inkDim, labelBackgroundColor: COLORS.ink },
      },
    };

    const mainContainer = el("main-chart");
    mainChart = LightweightCharts.createChart(mainContainer, baseOptions);
    candleSeries = mainChart.addCandlestickSeries({
      upColor: "rgba(0, 0, 0, 0)",
      downColor: COLORS.bear,
      borderVisible: true,
      borderUpColor: COLORS.bull,
      borderDownColor: COLORS.bear,
      wickUpColor: COLORS.bull,
      wickDownColor: COLORS.bear,
    });
    observeResize(mainContainer, mainChart);

    const rsiContainer = el("rsi-chart");
    rsiChart = LightweightCharts.createChart(rsiContainer, baseOptions);
    rsiSeries = rsiChart.addLineSeries({ color: COLORS.rsi, lineWidth: 2 });
    observeResize(rsiContainer, rsiChart);

    const macdContainer = el("macd-chart");
    macdChart = LightweightCharts.createChart(macdContainer, baseOptions);
    macdLineSeries = macdChart.addLineSeries({ color: COLORS.macd, lineWidth: 2 });
    macdSignalSeries = macdChart.addLineSeries({ color: COLORS.macdSignal, lineWidth: 1 });
    macdHistSeries = macdChart.addHistogramSeries({ color: "rgba(38, 49, 46, 0.35)" });
    observeResize(macdContainer, macdChart);

    const stochContainer = el("stoch-chart");
    stochChart = LightweightCharts.createChart(stochContainer, baseOptions);
    stochKSeries = stochChart.addLineSeries({ color: COLORS.rsi, lineWidth: 2 });
    stochDSeries = stochChart.addLineSeries({ color: COLORS.stamp, lineWidth: 1 });
    observeResize(stochContainer, stochChart);

    const equityContainer = el("equity-chart");
    equityChart = LightweightCharts.createChart(equityContainer, {
      ...baseOptions,
      rightPriceScale: { borderColor: COLORS.gridMajor },
      timeScale: { borderColor: COLORS.gridMajor, timeVisible: true, secondsVisible: false, visible: false },
    });
    equitySeries = equityChart.addAreaSeries({
      lineColor: COLORS.stamp,
      topColor: "rgba(138, 109, 59, 0.22)",
      bottomColor: "rgba(138, 109, 59, 0.02)",
      lineWidth: 2,
    });
    observeResize(equityContainer, equityChart);

    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range) return;
      rsiChart.timeScale().setVisibleLogicalRange(range);
      macdChart.timeScale().setVisibleLogicalRange(range);
      stochChart.timeScale().setVisibleLogicalRange(range);
    });

    mainChart.subscribeCrosshairMove(handleCrosshairMove);
    bindDrawClickCapture();
  }

  // Chart-relative point + bar time as last reported by the library's own
  // crosshair tracking — proven correct (it drives the working tooltip),
  // unlike hand-computing offsets from a raw DOM pointer event's
  // clientX/clientY, which don't line up with what coordinateToPrice/
  // coordinateToTime expect. The drawing-tools click capture below reuses
  // this instead of recomputing its own coordinates.
  let lastCrosshairPoint = null;

  function handleCrosshairMove(param) {
    lastCrosshairPoint = param.point && param.time !== undefined ? { y: param.point.y, time: param.time } : null;
    if (!param.point || param.time === undefined || !overlays.hitZones.length) {
      tooltipEl.classList.add("hidden");
      return;
    }
    const price = candleSeries.coordinateToPrice(param.point.y);
    if (price === null) {
      tooltipEl.classList.add("hidden");
      return;
    }
    const hit = overlays.hitZones.find(
      (z) => param.time >= z.start_time && param.time <= z.end_time && price <= z.price_high && price >= z.price_low
    );
    if (!hit) {
      tooltipEl.classList.add("hidden");
      return;
    }
    const rect = el("main-chart").getBoundingClientRect();
    tooltipEl.textContent = hit.label;
    tooltipEl.style.left = `${rect.left + param.point.x + 14}px`;
    tooltipEl.style.top = `${rect.top + param.point.y + 14}px`;
    tooltipEl.classList.remove("hidden");
  }

  function clearOverlays() {
    overlays.lineSeries.forEach((s) => {
      try {
        s.chart.removeSeries(s.series);
      } catch (e) {
        /* series already gone */
      }
    });
    overlays.priceLines.forEach(({ series, line }) => {
      try {
        series.removePriceLine(line);
      } catch (e) {
        /* already removed */
      }
    });
    overlays.primitives.forEach(({ series, primitive }) => {
      try {
        series.detachPrimitive(primitive);
      } catch (e) {
        /* already removed */
      }
    });
    overlays.lineSeries = [];
    overlays.priceLines = [];
    overlays.primitives = [];
    overlays.hitZones = [];
  }

  function seriesFromIndicatorValues(candles, values) {
    const out = [];
    for (let i = 0; i < candles.length; i++) {
      if (values[i] !== null && values[i] !== undefined) {
        out.push({ time: candles[i].time, value: values[i] });
      }
    }
    return out;
  }

  function findIndicator(indicators, name) {
    const found = indicators.find((s) => s.name === name);
    return found ? found.values : null;
  }

  function addLineOverlay(chart, series, target, chartRef) {
    overlays.lineSeries.push({ chart: chartRef, series });
  }

  function addRectangle(point1, point2, fillColor, borderColor, label) {
    const rect = new RectanglePrimitive(point1, point2, fillColor, borderColor);
    candleSeries.attachPrimitive(rect);
    overlays.primitives.push({ series: candleSeries, primitive: rect });
    if (label) {
      overlays.hitZones.push({
        price_low: Math.min(point1.price, point2.price),
        price_high: Math.max(point1.price, point2.price),
        start_time: Math.min(point1.time, point2.time),
        end_time: Math.max(point1.time, point2.time),
        label,
      });
    }
  }

  function pricePrecisionFor(price) {
    if (!price || price <= 0 || price >= 1) return { type: "price", precision: 2, minMove: 0.01 };
    const magnitude = Math.floor(Math.log10(price));
    const precision = Math.min(8, Math.max(2, -magnitude + 3));
    return { type: "price", precision, minMove: 1 / 10 ** precision };
  }

  // ---- Drawing tools (left rail next to the chart) ----
  // Drawings are placed with a click-to-collect flow (1 or 2 points
  // depending on the tool), rendered as chart primitives, and persisted in
  // localStorage per (asset_type, symbol) — client-side only, same scope as
  // TradingView's own free-tier drawings. No drag/resize of an already-placed
  // drawing in this first pass; removal is via the object list below the
  // rail, not by clicking the drawing itself (that needs canvas hit-testing,
  // scoped as a later iteration).
  const DRAW_TOOL_POINTS = { cursor: 0, trend_line: 2, hline: 1, rectangle: 2, range: 2, fib: 2, text: 1, arrow: 2 };
  const DRAW_TOOL_LABELS = {
    trend_line: "Linea di tendenza",
    hline: "Linea orizzontale",
    rectangle: "Rettangolo",
    range: "Misura (prezzo + tempo)",
    fib: "Ritracciamento Fibonacci",
    text: "Testo",
    arrow: "Freccia",
  };

  const drawState = {
    tool: "cursor",
    pending: [],
    drawings: [],
    attached: {}, // id -> { priceLine } | { primitives: [...] }
  };

  function drawStorageKey() {
    if (!state.data) return null;
    return `draw:${state.assetType}:${state.data.symbol}`;
  }

  function setDrawTool(tool) {
    drawState.tool = tool;
    drawState.pending = [];
    document.querySelectorAll(".draw-tool-btn").forEach((btn) => {
      btn.classList.toggle("selected", btn.dataset.drawTool === tool);
    });
    const container = el("main-chart");
    if (container) container.style.cursor = tool === "cursor" ? "default" : "crosshair";
    if (mainChart) mainChart.applyOptions({ handleScroll: tool === "cursor", handleScale: tool === "cursor" });
  }

  function formatRangeLabel(p1, p2) {
    const dPrice = p2.price - p1.price;
    const pct = p1.price !== 0 ? (dPrice / p1.price) * 100 : 0;
    const dSeconds = Math.abs(p2.time - p1.time);
    const dDays = dSeconds / 86400;
    const timeLabel = dDays >= 1 ? `${dDays.toFixed(1)}g` : `${Math.round(dSeconds / 3600)}h`;
    const sign = dPrice >= 0 ? "+" : "";
    return `${sign}${dPrice.toFixed(2)} (${sign}${pct.toFixed(2)}%) · ${timeLabel}`;
  }

  function attachDrawing(d) {
    if (!candleSeries) return;
    const color = COLORS.accent;
    if (d.type === "hline") {
      const line = candleSeries.createPriceLine({
        price: d.points[0].price,
        color,
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: d.text || "",
      });
      drawState.attached[d.id] = { priceLine: line };
      return;
    }
    const [p1, p2] = d.points;
    const primitives = [];
    if (d.type === "trend_line") {
      primitives.push(new LinePrimitive(p1, p2, color, 2, false));
    } else if (d.type === "arrow") {
      primitives.push(new LinePrimitive(p1, p2, color, 2, true));
    } else if (d.type === "rectangle") {
      primitives.push(new RectanglePrimitive(p1, p2, "rgba(31, 78, 107, 0.12)", color));
    } else if (d.type === "range") {
      primitives.push(new RectanglePrimitive(p1, p2, "rgba(138, 109, 59, 0.12)", COLORS.stamp));
      const topPoint = p1.price >= p2.price ? p1 : p2;
      primitives.push(new TextPrimitive(topPoint, d.text || "", COLORS.stamp));
    } else if (d.type === "fib") {
      primitives.push(new FibPrimitive(p1, p2, color));
    } else if (d.type === "text") {
      primitives.push(new TextPrimitive(p1, d.text || "", color));
    }
    primitives.forEach((prim) => candleSeries.attachPrimitive(prim));
    drawState.attached[d.id] = { primitives };
  }

  function detachDrawing(id) {
    const ref = drawState.attached[id];
    if (!ref) return;
    if (ref.priceLine) {
      try {
        candleSeries.removePriceLine(ref.priceLine);
      } catch (e) {
        /* already gone */
      }
    }
    if (ref.primitives) {
      ref.primitives.forEach((p) => {
        try {
          candleSeries.detachPrimitive(p);
        } catch (e) {
          /* already gone */
        }
      });
    }
    delete drawState.attached[id];
  }

  function clearAllDrawingPrimitives() {
    Object.keys(drawState.attached).forEach(detachDrawing);
  }

  function saveDrawings() {
    const key = drawStorageKey();
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(drawState.drawings));
    } catch (e) {
      /* storage unavailable/full — drawings just won't survive a reload */
    }
  }

  function renderDrawingsList() {
    const list = el("draw-list");
    if (!list) return;
    list.innerHTML = "";
    if (!drawState.drawings.length) {
      const li = document.createElement("li");
      li.className = "panel-hint";
      li.textContent = "Nessun disegno su questo grafico.";
      list.appendChild(li);
      return;
    }
    drawState.drawings.forEach((d) => {
      const li = document.createElement("li");
      li.className = "draw-list-item";
      const label = document.createElement("span");
      label.textContent = DRAW_TOOL_LABELS[d.type] || d.type;
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "draw-list-remove";
      removeBtn.textContent = "✕";
      removeBtn.addEventListener("click", () => removeDrawing(d.id));
      li.appendChild(label);
      li.appendChild(removeBtn);
      list.appendChild(li);
    });
  }

  function removeDrawing(id) {
    detachDrawing(id);
    drawState.drawings = drawState.drawings.filter((d) => d.id !== id);
    saveDrawings();
    renderDrawingsList();
  }

  function clearAllDrawings() {
    clearAllDrawingPrimitives();
    drawState.drawings = [];
    saveDrawings();
    renderDrawingsList();
  }

  function loadDrawingsForSymbol() {
    clearAllDrawingPrimitives();
    drawState.drawings = [];
    const key = drawStorageKey();
    if (key) {
      try {
        const raw = localStorage.getItem(key);
        if (raw) drawState.drawings = JSON.parse(raw);
      } catch (e) {
        drawState.drawings = [];
      }
    }
    drawState.drawings.forEach(attachDrawing);
    renderDrawingsList();
  }

  function finalizeDrawing() {
    const type = drawState.tool;
    const points = drawState.pending;
    drawState.pending = [];

    let text;
    if (type === "text") {
      text = window.prompt("Testo dell'annotazione:");
      if (!text) {
        setDrawTool("cursor");
        return;
      }
    } else if (type === "range") {
      text = formatRangeLabel(points[0], points[1]);
    }

    const drawing = { id: `d${Date.now()}${Math.random().toString(36).slice(2, 7)}`, type, points, text };
    drawState.drawings.push(drawing);
    attachDrawing(drawing);
    saveDrawings();
    renderDrawingsList();
    setDrawTool("cursor"); // single-shot, like TradingView's default (unlocked) behavior
  }

  // Lightweight Charts' own subscribeClick() disambiguates click-vs-drag
  // internally, and with panning enabled on the chart, ordinary mouse
  // jitter between press and release can get swallowed as a micro-pan
  // instead of firing a click — the exact symptom reported ("clicco e non
  // succede niente"). Capturing pointerdown/up directly, with our own
  // small-movement tolerance, sidesteps that entirely — and pan/zoom are
  // disabled for the duration so the chart doesn't drift under the cursor
  // while placing a point (see setDrawTool).
  const DRAW_CLICK_TOLERANCE_PX = 6;

  function bindDrawClickCapture() {
    const container = el("main-chart");
    let downPos = null;
    // Capture phase on document, not a bubble-phase listener on the
    // container: the chart library attaches its own pointer handlers
    // directly on its internal canvas for pan/zoom/crosshair, and those can
    // stop the event from ever bubbling back up to a container-level
    // listener. A capture-phase listener runs top-down before that,
    // guaranteeing delivery regardless of what the library does with it.
    document.addEventListener(
      "pointerdown",
      (e) => {
        if (drawState.tool === "cursor" || !container.contains(e.target)) return;
        downPos = { x: e.clientX, y: e.clientY };
      },
      true
    );
    document.addEventListener(
      "pointerup",
      (e) => {
        if (drawState.tool === "cursor" || !downPos || !state.data) {
          downPos = null;
          return;
        }
        const dx = e.clientX - downPos.x;
        const dy = e.clientY - downPos.y;
        downPos = null;
        if (Math.hypot(dx, dy) > DRAW_CLICK_TOLERANCE_PX) return; // was a drag, not a placement click
        if (!lastCrosshairPoint) return; // pointer never registered a valid chart position

        const price = candleSeries.coordinateToPrice(lastCrosshairPoint.y);
        const time = lastCrosshairPoint.time;
        if (price === null || time === undefined) return;

        drawState.pending.push({ time, price });
        if (drawState.pending.length >= DRAW_TOOL_POINTS[drawState.tool]) finalizeDrawing();
      },
      true
    );
  }

  function bindDrawRail() {
    document.querySelectorAll(".draw-tool-btn[data-draw-tool]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tool = btn.dataset.drawTool;
        setDrawTool(drawState.tool === tool ? "cursor" : tool);
      });
    });
    el("draw-clear-btn").addEventListener("click", () => {
      if (drawState.drawings.length && window.confirm("Cancellare tutti i disegni su questo grafico?")) {
        clearAllDrawings();
      }
    });
  }

  function render() {
    if (!state.data) return;
    clearOverlays();

    const tf = state.activeTimeframe;
    const analysis = state.data.timeframes[tf];
    const candles = analysis.candles;
    const lastTime = candles[candles.length - 1].time;
    const firstTime = candles[0].time;

    // Switching symbol/timeframe can jump price magnitude by orders of
    // magnitude (a $90,000 BTC chart vs. a $0.00001 microcap) — the default
    // fixed 2-decimal price format rounds small prices straight to 0.00.
    candleSeries.applyOptions({ priceFormat: pricePrecisionFor(candles[candles.length - 1].close) });
    candleSeries.setData(candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

    // --- price-scale indicator overlays ---
    if (state.layers.ema) {
      const ema20 = findIndicator(analysis.indicators, "EMA20");
      const ema50 = findIndicator(analysis.indicators, "EMA50");
      if (ema20) {
        const s = mainChart.addLineSeries({ color: COLORS.ema20, lineWidth: 1, priceLineVisible: false });
        s.setData(seriesFromIndicatorValues(candles, ema20));
        addLineOverlay(mainChart, s, null, mainChart);
      }
      if (ema50) {
        const s = mainChart.addLineSeries({ color: COLORS.ema50, lineWidth: 1, priceLineVisible: false });
        s.setData(seriesFromIndicatorValues(candles, ema50));
        addLineOverlay(mainChart, s, null, mainChart);
      }
    }
    if (state.layers.bbands) {
      ["BB_upper", "BB_mid", "BB_lower"].forEach((name) => {
        const vals = findIndicator(analysis.indicators, name);
        if (!vals) return;
        const s = mainChart.addLineSeries({ color: COLORS.bb, lineWidth: 1, priceLineVisible: false });
        s.setData(seriesFromIndicatorValues(candles, vals));
        addLineOverlay(mainChart, s, null, mainChart);
      });
    }
    if (state.layers.vwap) {
      const vals = findIndicator(analysis.indicators, "VWAP");
      if (vals) {
        const s = mainChart.addLineSeries({ color: COLORS.vwap, lineWidth: 1, priceLineVisible: false });
        s.setData(seriesFromIndicatorValues(candles, vals));
        addLineOverlay(mainChart, s, null, mainChart);
      }
    }

    // --- RSI / MACD sub-panes ---
    el("rsi-chart").classList.toggle("hidden", !state.layers.rsi);
    if (state.layers.rsi) {
      const vals = findIndicator(analysis.indicators, "RSI14");
      rsiSeries.setData(vals ? seriesFromIndicatorValues(candles, vals) : []);
    }
    el("macd-chart").classList.toggle("hidden", !state.layers.macd);
    if (state.layers.macd) {
      const macdVals = findIndicator(analysis.indicators, "MACD");
      const signalVals = findIndicator(analysis.indicators, "MACD_signal");
      const histVals = findIndicator(analysis.indicators, "MACD_hist");
      macdLineSeries.setData(macdVals ? seriesFromIndicatorValues(candles, macdVals) : []);
      macdSignalSeries.setData(signalVals ? seriesFromIndicatorValues(candles, signalVals) : []);
      if (histVals) {
        macdHistSeries.setData(
          seriesFromIndicatorValues(candles, histVals).map((d) => ({
            time: d.time,
            value: d.value,
            color: d.value >= 0 ? "rgba(46, 92, 62, 0.55)" : "rgba(140, 47, 31, 0.55)",
          }))
        );
      } else {
        macdHistSeries.setData([]);
      }
    }

    el("stoch-chart").classList.toggle("hidden", !state.layers.stoch);
    if (state.layers.stoch) {
      const kVals = findIndicator(analysis.indicators, "STOCH_K");
      const dVals = findIndicator(analysis.indicators, "STOCH_D");
      stochKSeries.setData(kVals ? seriesFromIndicatorValues(candles, kVals) : []);
      stochDSeries.setData(dVals ? seriesFromIndicatorValues(candles, dVals) : []);
    }

    // --- structure / liquidity overlays ---
    analysis.levels.forEach((lvl) => {
      const isZone = lvl.type === "order_block" || lvl.type === "fvg";
      const layerKey = lvl.type === "order_block" ? "order_block" : lvl.type === "fvg" ? "fvg" : lvl.type === "eqh" || lvl.type === "eql" ? "liquidity" : "structure";
      if (!state.layers[layerKey]) return;

      const isBullish = lvl.direction === "bullish";
      const fill = isBullish ? COLORS.bullFill : COLORS.bearFill;
      const border = isBullish ? COLORS.bullBorder : COLORS.bearBorder;
      const endTime = lvl.end_time ?? lastTime;

      if (isZone) {
        addRectangle(
          { time: lvl.start_time, price: lvl.price_high },
          { time: endTime, price: lvl.price_low },
          fill,
          border,
          lvl.label
        );
      } else {
        const line = candleSeries.createPriceLine({
          price: lvl.price_high,
          color: border,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: lvl.label,
        });
        overlays.priceLines.push({ series: candleSeries, line });
      }
    });

    if (state.layers.confluence) {
      state.data.confluence_zones.forEach((z) => {
        addRectangle(
          { time: firstTime, price: z.price_high },
          { time: lastTime, price: z.price_low },
          COLORS.confluenceFill,
          COLORS.confluenceBorder,
          z.label
        );
      });
    }

    renderSummary();
    renderStrategy();
    renderBacktest();
    resizeAllCharts();
    mainChart.timeScale().fitContent();
  }

  function renderStrategy() {
    const allSignals = [];
    ["htf", "mtf", "ltf"].forEach((tf) => {
      const states = state.data.strategies[tf];
      if (!states || !states.length) return;
      states[0].signals.forEach((sig) => allSignals.push({ ...sig, tf }));
    });
    allSignals.sort((a, b) => a.time - b.time);

    const activeState = (state.data.strategies[state.activeTimeframe] || [])[0];
    const badge = el("strategy-position-badge");
    if (activeState) {
      badge.textContent = activeState.position.toUpperCase();
      badge.className = "position-badge " + activeState.position;
    }

    const log = el("strategy-alert-log");
    log.innerHTML = "";
    allSignals.slice(-40).forEach((sig) => {
      const li = document.createElement("li");
      li.className = sig.type.includes("long") ? "long-signal" : "short-signal";
      const time = new Date(sig.time * 1000).toLocaleString("it-IT");
      li.innerHTML = `[${sig.tf.toUpperCase()}] ${sig.label} — ${sig.price.toPrecision(6)}<span class="alert-time">${time}</span>`;
      log.appendChild(li);
    });

    if (el("strategy-markers-toggle").checked && activeState) {
      candleSeries.setMarkers(buildStrategyMarkers(activeState.signals));
    } else {
      candleSeries.setMarkers([]);
    }

    notifyNewAlerts(allSignals);
  }

  // Entry/exit/flip need to read unambiguously at a glance: shape says
  // in-or-out (triangle vs. circle), color says which side (bull green vs.
  // bear red — flips get the stamp accent since they're neither purely "in"
  // nor "out"), and the label spells it out instead of a bare cryptic letter.
  function buildStrategyMarkers(signals) {
    return signals.map((sig) => {
      const isLongSide = sig.type.includes("long");
      if (sig.type.startsWith("entry")) {
        return {
          time: sig.time,
          position: isLongSide ? "belowBar" : "aboveBar",
          color: isLongSide ? COLORS.bullBorder : COLORS.bearBorder,
          shape: isLongSide ? "arrowUp" : "arrowDown",
          text: isLongSide ? "IN long" : "IN short",
        };
      }
      if (sig.type.startsWith("exit")) {
        return {
          time: sig.time,
          position: isLongSide ? "aboveBar" : "belowBar",
          color: isLongSide ? COLORS.bullBorder : COLORS.bearBorder,
          shape: "circle",
          text: "OUT",
        };
      }
      // flip_to_long / flip_to_short: closes one side and opens the other in
      // the same bar — mark it distinctly rather than as a plain entry.
      const flippingToLong = sig.type === "flip_to_long";
      return {
        time: sig.time,
        position: flippingToLong ? "belowBar" : "aboveBar",
        color: COLORS.stamp,
        shape: flippingToLong ? "arrowUp" : "arrowDown",
        text: flippingToLong ? "FLIP long" : "FLIP short",
      };
    });
  }

  function notifyNewAlerts(allSignals) {
    const isFirstPass = !state.alertsSeeded;
    allSignals.forEach((sig) => {
      const key = `${state.data.symbol}|${sig.tf}|${sig.time}|${sig.type}`;
      if (state.seenAlertKeys.has(key)) return;
      state.seenAlertKeys.add(key);
      if (isFirstPass) return;
      if (
        el("strategy-notify-toggle").checked &&
        "Notification" in window &&
        Notification.permission === "granted"
      ) {
        new Notification(`${state.data.symbol} [${sig.tf.toUpperCase()}] Lorenzo`, {
          body: `${sig.label} @ ${sig.price}`,
        });
      }
    });
    state.alertsSeeded = true;
  }

  function renderBacktest() {
    const bt = state.data.backtests[state.activeTimeframe];
    const statsEl = el("backtest-stats");
    statsEl.innerHTML = "";
    if (!bt) return;

    const returnClass = bt.total_return_pct >= 0 ? "positive" : "negative";
    const stats = [
      ["Rendimento", `${bt.total_return_pct >= 0 ? "+" : ""}${bt.total_return_pct.toFixed(1)}%`, returnClass],
      ["Equity finale", bt.final_equity.toLocaleString("it-IT", { maximumFractionDigits: 0 }), ""],
      ["Trade", bt.num_trades, ""],
      ["Win rate", bt.win_rate_pct !== null ? `${bt.win_rate_pct.toFixed(0)}%` : "—", ""],
      ["Max drawdown", `-${bt.max_drawdown_pct.toFixed(1)}%`, "negative"],
      ["Profit factor", bt.profit_factor !== null ? bt.profit_factor.toFixed(2) : "—", ""],
    ];
    stats.forEach(([label, value, cls]) => {
      const div = document.createElement("div");
      div.className = "stat";
      div.innerHTML = `<div class="stat-label">${label}</div><div class="stat-value ${cls}">${value}</div>`;
      statsEl.appendChild(div);
    });

    equitySeries.setData(bt.equity_curve.map(([time, equity]) => ({ time, value: equity })));
    equityChart.timeScale().fitContent();
  }

  function getStrategyAndBacktestQuery() {
    const form = el("params-form");
    const data = new FormData(form);
    const params = new URLSearchParams();
    ["average", "len", "slopeFlen", "slopeSlen", "trendfilterperiod", "trendfiltertype",
      "volatilitystdevlength", "volatilitystdevmalength", "initial_capital", "qty_pct_of_equity",
      "commission_pct", "slippage_pct", "stop_loss_pct", "take_profit_pct"].forEach((name) => {
      params.set(name, data.get(name));
    });
    params.set("trendfilter", form.elements["trendfilter"].checked);
    params.set("volatilityfilter", form.elements["volatilityfilter"].checked);
    params.set("enable_divergence", form.elements["enable_divergence"].checked);
    params.set("enable_contraction", form.elements["enable_contraction"].checked);
    params.set("enable_range_bounce", form.elements["enable_range_bounce"].checked);
    params.set("strategy_name", el("active-strategy-select").value);
    return params.toString();
  }

  function renderSummary() {
    const summary = state.data.summary;
    el("summary-text").textContent = summary.text;

    const ltcList = el("long-term-context");
    ltcList.innerHTML = "";
    summary.long_term_context.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      ltcList.appendChild(li);
    });

    const readoutList = el("indicator-readout");
    readoutList.innerHTML = "";
    summary.indicator_readout.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      readoutList.appendChild(li);
    });

    const list = el("confluence-list");
    list.innerHTML = "";
    if (summary.top_confluence_zones.length === 0) {
      const li = document.createElement("li");
      li.textContent = "Nessuna zona di confluenza multi-timeframe rilevata al momento.";
      list.appendChild(li);
    }
    summary.top_confluence_zones.forEach((z) => {
      const li = document.createElement("li");
      const range = document.createElement("div");
      range.className = "cz-range";
      range.textContent = `${z.price_low.toPrecision(6)} — ${z.price_high.toPrecision(6)}`;
      const label = document.createElement("div");
      label.textContent = z.label;
      li.appendChild(label);
      li.appendChild(range);
      list.appendChild(li);
    });
  }

  function showError(message) {
    const banner = el("error-banner");
    banner.textContent = `${message} Verifica il ticker e il tipo di asset selezionato (Azioni/Crypto).`;
    banner.classList.remove("hidden");
  }

  function clearError() {
    el("error-banner").classList.add("hidden");
  }

  function applyLiveCandle(timeframe, candle) {
    if (!state.data || !state.data.timeframes[timeframe]) return;
    const candles = state.data.timeframes[timeframe].candles;
    const last = candles[candles.length - 1];
    if (last && last.time === candle.time) {
      candles[candles.length - 1] = candle;
    } else if (!last || candle.time > last.time) {
      candles.push(candle);
    } else {
      return; // out-of-order/stale tick
    }
    if (timeframe === state.activeTimeframe) {
      try {
        candleSeries.update(candle);
      } catch (err) {
        /* rare out-of-order update from the live feed; next tick self-corrects */
      }
    }
  }

  function disconnectLiveFeed() {
    if (state.liveSocket) {
      const ws = state.liveSocket;
      state.liveSocket = null; // cleared first so the socket's own close handler won't reconnect
      ws.close();
    }
    if (state.liveRefreshTimer) {
      clearInterval(state.liveRefreshTimer);
      state.liveRefreshTimer = null;
    }
    el("live-badge").classList.add("hidden");
    el("polling-badge").classList.add("hidden");
  }

  function intervalQuery() {
    const iv = getSelectedIntervals();
    return `htf_interval=${iv.htf}&mtf_interval=${iv.mtf}&ltf_interval=${iv.ltf}`;
  }

  function connectLiveFeed(symbol) {
    disconnectLiveFeed();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(
      `${proto}://${location.host}/ws/live?symbol=${encodeURIComponent(symbol)}&${intervalQuery()}`
    );
    state.liveSocket = ws;

    ws.addEventListener("open", () => el("live-badge").classList.remove("hidden"));
    ws.addEventListener("message", (event) => {
      try {
        const msg = JSON.parse(event.data);
        applyLiveCandle(msg.timeframe, msg.candle);
      } catch (err) {
        /* ignore malformed frame */
      }
    });
    ws.addEventListener("close", () => {
      el("live-badge").classList.add("hidden");
      if (state.liveSocket === ws && state.assetType === "crypto" && state.data && state.data.symbol === symbol) {
        setTimeout(() => connectLiveFeed(symbol), 3000);
      }
    });
    ws.addEventListener("error", () => ws.close());
  }

  async function silentRefresh(symbol) {
    if (!state.data || state.data.symbol !== symbol) return;
    try {
      const url = `/api/analyze?symbol=${encodeURIComponent(symbol)}&asset_type=${state.assetType}&exchange=${state.cryptoExchange}&${intervalQuery()}&${getStrategyAndBacktestQuery()}`;
      const resp = await fetch(url);
      if (!resp.ok) return;
      state.data = await resp.json();
      render();
    } catch (err) {
      /* keep last known state; live ticks keep flowing independently */
    }
  }

  async function runAnalysis(symbol) {
    clearError();
    el("loading").classList.remove("hidden");
    el("empty-state").classList.add("hidden");
    el("chart-wrap").classList.add("hidden");
    el("search-btn").disabled = true;
    disconnectLiveFeed();

    try {
      const url = `/api/analyze?symbol=${encodeURIComponent(symbol)}&asset_type=${state.assetType}&exchange=${state.cryptoExchange}&${intervalQuery()}&${getStrategyAndBacktestQuery()}`;
      const resp = await fetch(url);
      const body = await resp.json();
      if (!resp.ok) {
        const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        throw new Error(detail || `Errore ${resp.status}`);
      }
      state.data = body;
      state.seenAlertKeys = new Set();
      state.alertsSeeded = false;
      if (state.pineActive) clearPineOverride();
      el("chart-wrap").classList.remove("hidden");
      resizeAllCharts();
      render();
      loadDrawingsForSymbol();
      // Live WS streaming is only wired up for MEXC today; every crypto
      // symbol still gets the periodic refresh below regardless of exchange.
      if (state.assetType === "crypto" && state.cryptoExchange === "mexc") {
        connectLiveFeed(body.symbol);
      }
      if (state.assetType === "crypto") {
        state.liveRefreshTimer = setInterval(() => silentRefresh(body.symbol), 60000);
        // No WebSocket wired up for Binance yet — say so plainly instead of
        // leaving the user guessing whether the chart is updating at all.
        if (state.cryptoExchange !== "mexc") {
          el("polling-badge").classList.remove("hidden");
        }
      }
    } catch (err) {
      showError(err.message || "Errore durante l'analisi del ticker.");
      el("empty-state").classList.remove("hidden");
    } finally {
      el("loading").classList.add("hidden");
      el("search-btn").disabled = false;
    }
  }

  let suggestTimer = null;

  async function fetchSuggestions(query) {
    try {
      const url = `/api/symbols?query=${encodeURIComponent(query)}`;
      const resp = await fetch(url);
      state.suggestions = resp.ok ? await resp.json() : [];
    } catch (err) {
      state.suggestions = [];
    }
    state.activeSuggestionIndex = -1;
    renderSuggestions();
  }

  function positionSuggestions() {
    const list = el("ticker-suggestions");
    const rect = el("ticker-input").getBoundingClientRect();
    list.style.left = `${rect.left}px`;
    list.style.top = `${rect.bottom + 4}px`;
    list.style.width = `${rect.width}px`;
  }

  function renderSuggestions() {
    const list = el("ticker-suggestions");
    list.innerHTML = "";
    if (!state.suggestions.length) {
      list.classList.add("hidden");
      return;
    }
    positionSuggestions();
    state.suggestions.forEach((item, i) => {
      const li = document.createElement("li");
      li.className = i === state.activeSuggestionIndex ? "active" : "";
      const main = document.createElement("span");
      main.className = "sug-main";
      const sym = document.createElement("span");
      sym.className = "sug-symbol";
      sym.textContent = item.symbol;
      const name = document.createElement("span");
      name.className = "sug-name";
      name.textContent = item.name || "";
      main.appendChild(sym);
      main.appendChild(name);
      const exchange = document.createElement("span");
      exchange.className = "sug-exchange sug-exchange-" + item.provider;
      exchange.textContent = item.exchange;
      if (item.provider === "mexc" || item.provider === "binance") {
        exchange.title = "Prezzi e livelli calcolati su questo exchange — possono differire leggermente da altri exchange per lo stesso simbolo.";
      }
      li.appendChild(main);
      li.appendChild(exchange);
      // mousedown (not click) fires before the input's blur handler hides the list
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectSuggestion(item);
      });
      list.appendChild(li);
    });
    list.classList.remove("hidden");
  }

  function hideSuggestions() {
    state.suggestions = [];
    state.activeSuggestionIndex = -1;
    const list = el("ticker-suggestions");
    list.classList.add("hidden");
    list.innerHTML = "";
  }

  function selectSuggestion(item) {
    el("ticker-input").value = item.symbol;
    state.assetType = item.asset_type;
    state.cryptoExchange = item.provider === "binance" ? "binance" : "mexc";
    hideSuggestions();
    runAnalysis(item.symbol);
  }

  function bindTickerAutocomplete() {
    const input = el("ticker-input");

    input.addEventListener("input", () => {
      const value = input.value.trim();
      clearTimeout(suggestTimer);
      if (!value) {
        hideSuggestions();
        return;
      }
      suggestTimer = setTimeout(() => fetchSuggestions(value), 300);
    });

    input.addEventListener("keydown", (e) => {
      if (el("ticker-suggestions").classList.contains("hidden")) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        state.activeSuggestionIndex = Math.min(state.activeSuggestionIndex + 1, state.suggestions.length - 1);
        renderSuggestions();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        state.activeSuggestionIndex = Math.max(state.activeSuggestionIndex - 1, 0);
        renderSuggestions();
      } else if (e.key === "Enter") {
        if (state.activeSuggestionIndex >= 0) {
          e.preventDefault();
          selectSuggestion(state.suggestions[state.activeSuggestionIndex]);
        } else {
          hideSuggestions();
        }
      } else if (e.key === "Escape") {
        hideSuggestions();
      }
    });

    input.addEventListener("blur", () => {
      setTimeout(hideSuggestions, 150);
    });
  }

  // ---- Script Pine: upload/parse/apply, editor via CodeMirror ----

  let pineCM = null;

  function initPineEditor() {
    pineCM = CodeMirror.fromTextArea(el("pine-source"), {
      lineNumbers: true,
      lineWrapping: false,
      styleActiveLine: true,
      indentUnit: 4,
      tabSize: 4,
      viewportMargin: Infinity,
    });
  }

  async function loadPineScripts() {
    const resp = await fetch("/api/pinescript");
    state.pineScripts = resp.ok ? await resp.json() : [];
    const select = el("pine-script-select");
    const current = select.value;
    select.innerHTML = '<option value="">— Nuovo script —</option>';
    state.pineScripts.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.name;
      select.appendChild(opt);
    });
    if (state.pineScripts.some((s) => s.id === current)) select.value = current;
  }

  function pineSetStatus(elId, text, cls) {
    const node = el(elId);
    node.textContent = text || "";
    node.className = "pine-status" + (cls ? " " + cls : "");
  }

  function renderPineParamsForm(script) {
    state.activePineParams = script.params;
    state.activePineIsStrategy = script.is_strategy_style;
    const container = el("pine-params-fields");
    container.innerHTML = "";
    script.params.forEach((p) => {
      const row = document.createElement("div");
      row.className = "pine-param-row";
      let input;
      if (p.kind === "bool") {
        input = `<input type="checkbox" data-pine-param="${p.var_name}" ${p.default ? "checked" : ""} />`;
      } else if (p.kind === "int" || p.kind === "float") {
        const step = p.kind === "int" ? "1" : "any";
        input = `<input type="number" step="${step}" data-pine-param="${p.var_name}" value="${p.default ?? ""}" />`;
      } else {
        input = `<input type="text" data-pine-param="${p.var_name}" value="${p.default ?? ""}" />`;
      }
      row.innerHTML = `<label>${p.title}</label>${input}`;
      container.appendChild(row);
    });
    el("pine-params-form").classList.remove("hidden");
    el("pine-delete-btn").classList.remove("hidden");
    el("pine-signal-mapping").classList.toggle("hidden", script.is_strategy_style);
  }

  function collectPineParams() {
    const params = {};
    document.querySelectorAll("[data-pine-param]").forEach((input) => {
      const name = input.dataset.pineParam;
      if (input.type === "checkbox") params[name] = input.checked;
      else if (input.type === "number") params[name] = input.value === "" ? null : parseFloat(input.value);
      else params[name] = input.value;
    });
    return params;
  }

  function collectSignalMap() {
    const map = {};
    document.querySelectorAll("#pine-signal-mapping select[data-role]").forEach((select) => {
      if (select.value) map[select.dataset.role] = select.value;
    });
    return map;
  }

  function populateSignalMappingCandidates(candidates) {
    document.querySelectorAll("#pine-signal-mapping select[data-role]").forEach((select) => {
      const current = select.value;
      select.innerHTML = '<option value="">—</option>';
      candidates.forEach((c) => {
        const opt = document.createElement("option");
        opt.value = c.name;
        opt.textContent = `${c.name} (${c.true_count}x)`;
        select.appendChild(opt);
      });
      if (candidates.some((c) => c.name === current)) select.value = current;
    });
    el("pine-signal-mapping").classList.remove("hidden");
  }

  async function analyzePineSource() {
    const name = el("pine-script-name").value.trim() || "Script senza nome";
    const source = pineCM.getValue();
    if (!source.trim()) {
      pineSetStatus("pine-parse-status", "Incolla o carica uno script prima di analizzare.", "error");
      return;
    }
    pineSetStatus("pine-parse-status", "Analisi in corso…", "");
    try {
      const resp = await fetch("/api/pinescript", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, source }),
      });
      const body = await resp.json();
      if (!resp.ok) {
        pineSetStatus("pine-parse-status", typeof body.detail === "string" ? body.detail : "Errore di parsing.", "error");
        return;
      }
      pineSetStatus("pine-parse-status", `Script valido — ${body.params.length} parametri rilevati.`, "ok");
      await loadPineScripts();
      el("pine-script-select").value = body.id;
      renderPineParamsForm(body);
    } catch (err) {
      pineSetStatus("pine-parse-status", "Errore di rete durante l'analisi.", "error");
    }
  }

  async function selectPineScript(id) {
    if (!id) {
      state.activePineScriptId = null;
      el("pine-params-form").classList.add("hidden");
      el("pine-delete-btn").classList.add("hidden");
      el("pine-script-name").value = "";
      pineCM.setValue("");
      return;
    }
    const resp = await fetch(`/api/pinescript/${id}`);
    if (!resp.ok) return;
    const body = await resp.json();
    state.activePineScriptId = id;
    el("pine-script-name").value = body.name;
    pineCM.setValue(body.source);
    renderPineParamsForm(body);
    pineSetStatus("pine-parse-status", `Script caricato — ${body.params.length} parametri.`, "ok");
  }

  async function applyPineScript() {
    if (!state.activePineScriptId) {
      pineSetStatus("pine-run-status", "Analizza e salva uno script prima di applicarlo.", "error");
      return;
    }
    if (!state.data) {
      pineSetStatus("pine-run-status", "Cerca prima un ticker.", "error");
      return;
    }
    pineSetStatus("pine-run-status", "Esecuzione script…", "");
    try {
      const resp = await fetch(`/api/pinescript/${state.activePineScriptId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: state.data.symbol,
          asset_type: state.assetType,
          exchange: state.cryptoExchange,
          timeframe: state.activeTimeframe,
          params: collectPineParams(),
          signal_map: state.activePineIsStrategy ? null : collectSignalMap(),
        }),
      });
      const body = await resp.json();
      if (!resp.ok) {
        pineSetStatus("pine-run-status", typeof body.detail === "string" ? body.detail : "Errore di esecuzione.", "error");
        return;
      }
      if (body.needs_mapping) {
        populateSignalMappingCandidates(body.candidates);
        pineSetStatus("pine-run-status", body.warning || "Seleziona la mappatura dei segnali.", "error");
        return;
      }
      state.pineActive = true;
      state.pineLastResult = body;
      el("pine-clear-btn").classList.remove("hidden");
      renderPineStrategy(body.strategy);
      renderPineBacktest(body.backtest);
      pineSetStatus("pine-run-status", "Applicato al grafico.", "ok");
    } catch (err) {
      pineSetStatus("pine-run-status", "Errore di rete durante l'esecuzione.", "error");
    }
  }

  function clearPineOverride() {
    state.pineActive = false;
    state.pineLastResult = null;
    el("pine-clear-btn").classList.add("hidden");
    pineSetStatus("pine-run-status", "", "");
    if (state.data) {
      renderStrategy();
      renderBacktest();
    }
  }

  function renderPineStrategy(strategyState) {
    const badge = el("strategy-position-badge");
    badge.textContent = strategyState.position.toUpperCase();
    badge.className = "position-badge " + strategyState.position;

    const log = el("strategy-alert-log");
    log.innerHTML = "";
    strategyState.signals.slice(-40).forEach((sig) => {
      const li = document.createElement("li");
      li.className = sig.type.includes("long") ? "long-signal" : "short-signal";
      const time = new Date(sig.time * 1000).toLocaleString("it-IT");
      li.innerHTML = `[${state.activeTimeframe.toUpperCase()}] ${sig.label} — ${sig.price.toPrecision(6)}<span class="alert-time">${time}</span>`;
      log.appendChild(li);
    });

    if (el("strategy-markers-toggle").checked) {
      candleSeries.setMarkers(buildStrategyMarkers(strategyState.signals));
    } else {
      candleSeries.setMarkers([]);
    }
  }

  function renderPineBacktest(bt) {
    const statsEl = el("backtest-stats");
    statsEl.innerHTML = "";
    const returnClass = bt.total_return_pct >= 0 ? "positive" : "negative";
    const stats = [
      ["Rendimento", `${bt.total_return_pct >= 0 ? "+" : ""}${bt.total_return_pct.toFixed(1)}%`, returnClass],
      ["Equity finale", bt.final_equity.toLocaleString("it-IT", { maximumFractionDigits: 0 }), ""],
      ["Trade", bt.num_trades, ""],
      ["Win rate", bt.win_rate_pct !== null ? `${bt.win_rate_pct.toFixed(0)}%` : "—", ""],
      ["Max drawdown", `-${bt.max_drawdown_pct.toFixed(1)}%`, "negative"],
      ["Profit factor", bt.profit_factor !== null ? bt.profit_factor.toFixed(2) : "—", ""],
    ];
    stats.forEach(([label, value, cls]) => {
      const div = document.createElement("div");
      div.className = "stat";
      div.innerHTML = `<div class="stat-label">${label}</div><div class="stat-value ${cls}">${value}</div>`;
      statsEl.appendChild(div);
    });
    equitySeries.setData(bt.equity_curve.map(([time, equity]) => ({ time, value: equity })));
    equityChart.timeScale().fitContent();
  }

  function bindPineUI() {
    el("pine-file-input").addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        pineCM.setValue(reader.result);
        if (!el("pine-script-name").value.trim()) {
          el("pine-script-name").value = file.name.replace(/\.(pine|txt)$/i, "");
        }
      };
      reader.readAsText(file);
    });

    el("pine-analyze-btn").addEventListener("click", analyzePineSource);

    el("pine-script-select").addEventListener("change", (e) => selectPineScript(e.target.value));

    el("pine-delete-btn").addEventListener("click", async () => {
      if (!state.activePineScriptId) return;
      if (!confirm("Eliminare questo script?")) return;
      await fetch(`/api/pinescript/${state.activePineScriptId}`, { method: "DELETE" });
      state.activePineScriptId = null;
      el("pine-params-form").classList.add("hidden");
      el("pine-delete-btn").classList.add("hidden");
      el("pine-script-name").value = "";
      pineCM.setValue("");
      loadPineScripts();
    });

    el("pine-params-form").addEventListener("submit", (e) => {
      e.preventDefault();
      applyPineScript();
    });

    el("pine-clear-btn").addEventListener("click", clearPineOverride);
  }

  // Mobile app-shell: the sidebar/summary-panel become bottom-sheet drawers
  // opened via the bottom tab bar, closed by tapping "Grafico", the backdrop,
  // or the same tab again — mirrors how TradingView's own mobile app keeps
  // the chart full-screen with menus tucked away until asked for.
  function closeMobileDrawers() {
    el("levels-panel").classList.remove("mobile-open");
    el("script-panel").classList.remove("mobile-open");
    document.querySelector(".right-panel").classList.remove("mobile-open");
    el("mobile-drawer-backdrop").classList.add("hidden");
    document.querySelectorAll(".mobile-nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelector('.mobile-nav-btn[data-mobile-target="chart"]').classList.add("active");
  }

  // Desktop-only: a rail icon opens/closes its panel as a flyout that
  // reflows the chart (not an overlay) — click the icon again, click
  // anywhere outside it, or open the other rail panel, to close it.
  const RAIL_PANELS = [
    ["rail-levels-btn", "levels-panel"],
    ["rail-script-btn", "script-panel"],
  ];

  function bindRail() {
    RAIL_PANELS.forEach(([btnId, panelId]) => {
      const btn = el(btnId);
      const panel = el(panelId);
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const opening = !panel.classList.contains("open");
        RAIL_PANELS.forEach(([otherBtnId, otherPanelId]) => {
          el(otherPanelId).classList.remove("open");
          el(otherBtnId).classList.remove("active");
        });
        panel.classList.toggle("open", opening);
        btn.classList.toggle("active", opening);
        resizeAllCharts();
      });
    });
    document.addEventListener("click", (e) => {
      RAIL_PANELS.forEach(([btnId, panelId]) => {
        const btn = el(btnId);
        const panel = el(panelId);
        if (!panel.classList.contains("open")) return;
        if (panel.contains(e.target) || btn.contains(e.target)) return;
        panel.classList.remove("open");
        btn.classList.remove("active");
        resizeAllCharts();
      });
    });
  }

  // Used by links that need to open a specific panel outside the rail/bottom
  // nav (e.g. the "Script Pine personalizzato" link inside the Alert tab) —
  // works the same on desktop (flyout via the matching rail button) and
  // mobile (bottom-sheet drawer), whichever this viewport is currently using.
  function openPanel(panelId) {
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    if (isMobile) {
      closeMobileDrawers();
      el(panelId).classList.add("mobile-open");
      el("mobile-drawer-backdrop").classList.remove("hidden");
    } else {
      RAIL_PANELS.forEach(([btnId, pid]) => {
        el(pid).classList.toggle("open", pid === panelId);
        el(btnId).classList.toggle("active", pid === panelId);
      });
      resizeAllCharts();
    }
  }

  function bindTabs() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        const name = tab.dataset.tab;
        document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
        document.querySelectorAll(".tab-content").forEach((c) => {
          c.classList.toggle("active", c.dataset.tabContent === name);
        });
        resizeAllCharts();
      });
    });
  }

  function bindMobileNav() {
    const targets = { levels: el("levels-panel"), panel: document.querySelector(".right-panel") };
    document.querySelectorAll(".mobile-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.mobileTarget;
        if (target === "chart") {
          closeMobileDrawers();
          resizeAllCharts();
          return;
        }
        const panel = targets[target];
        const alreadyOpen = panel.classList.contains("mobile-open");
        closeMobileDrawers();
        if (!alreadyOpen) {
          panel.classList.add("mobile-open");
          el("mobile-drawer-backdrop").classList.remove("hidden");
          btn.classList.add("active");
        }
      });
    });
    el("mobile-drawer-backdrop").addEventListener("click", () => {
      closeMobileDrawers();
      resizeAllCharts();
    });

    document.querySelectorAll("[data-close-drawer]").forEach((btn) => {
      btn.addEventListener("click", () => {
        closeMobileDrawers();
        resizeAllCharts();
      });
    });
  }

  function bindUI() {
    document.querySelectorAll("[data-layer]").forEach((input) => {
      input.addEventListener("change", () => {
        state.layers[input.dataset.layer] = input.checked;
        render();
      });
    });

    el("search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const symbol = el("ticker-input").value.trim();
      if (!symbol) return;
      // No suggestion explicitly picked (e.g. hit Enter right away) — if the
      // typed text exactly matches a suggestion already fetched, use its
      // asset type/exchange instead of falling back to whatever was set last.
      const exact = state.suggestions.find((s) => s.symbol.toLowerCase() === symbol.toLowerCase());
      if (exact) {
        state.assetType = exact.asset_type;
        state.cryptoExchange = exact.provider === "binance" ? "binance" : "mexc";
      }
      hideSuggestions();
      runAnalysis(symbol);
    });

    bindTickerAutocomplete();

    el("interval-primary").addEventListener("change", () => {
      if (state.pineActive) clearPineOverride();
      if (state.data) runAnalysis(state.data.symbol);
    });

    el("params-form").addEventListener("submit", (e) => {
      e.preventDefault();
      if (state.data) runAnalysis(state.data.symbol);
    });

    el("active-strategy-select").addEventListener("change", () => {
      if (state.data) runAnalysis(state.data.symbol);
    });

    document.querySelectorAll(".wl-asset-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".wl-asset-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.watchlistAssetType = btn.dataset.watchlistAsset;
        el("watchlist-exchange").classList.toggle("hidden", state.watchlistAssetType !== "crypto");
      });
    });

    el("watchlist-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const symbol = el("watchlist-symbol").value.trim();
      if (!symbol) return;
      await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          asset_type: state.watchlistAssetType,
          exchange: el("watchlist-exchange").value,
          interval: el("watchlist-interval").value,
        }),
      });
      el("watchlist-symbol").value = "";
      loadWatchlist();
    });

    el("open-script-from-alert").addEventListener("click", (e) => {
      e.stopPropagation();
      openPanel("script-panel");
    });

    el("strategy-markers-toggle").addEventListener("change", () => {
      if (state.data) renderStrategy();
    });

    el("strategy-notify-toggle").addEventListener("change", async (e) => {
      if (!e.target.checked) return;
      if (!("Notification" in window)) {
        e.target.checked = false;
        return;
      }
      if (Notification.permission === "default") {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") e.target.checked = false;
      } else if (Notification.permission === "denied") {
        e.target.checked = false;
      }
    });

    el("log-scale-toggle").addEventListener("change", (e) => {
      state.logScale = e.target.checked;
      mainChart.priceScale("right").applyOptions({
        mode: state.logScale ? LightweightCharts.PriceScaleMode.Logarithmic : LightweightCharts.PriceScaleMode.Normal,
      });
    });
  }

  // On phones the toolbar has no room to also carry the timeframe/strategy/
  // log-scale controls without burying the chart below the fold (a TradingView
  // mobile screen shows almost nothing but the chart). Relocate that one group
  // — moving the real nodes, not cloning them, so there's still exactly one
  // #interval-primary etc. in the DOM — into the Livelli drawer on mobile, and
  // back into the toolbar on desktop.
  function relocateChartSettings() {
    const group = el("chart-settings-group");
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    const targetParent = isMobile ? el("levels-panel") : document.querySelector(".toolbar");
    if (group.parentElement === targetParent) return;
    if (isMobile) {
      const header = targetParent.querySelector(".drawer-header");
      targetParent.insertBefore(group, header.nextSibling);
    } else {
      const spacer = targetParent.querySelector(".toolbar-spacer");
      targetParent.insertBefore(group, spacer);
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    populateIntervalSelects();
    loadWatchlist();
    initCharts();
    bindUI();
    bindMobileNav();
    bindRail();
    bindTabs();
    bindDrawRail();
    initPineEditor();
    bindPineUI();
    loadPineScripts();
    relocateChartSettings();
    // active-strategy-select must be populated before the auto-load below
    // reads its value, or the request goes out with an empty strategy_name.
    await populateStrategySelects();
    // A real trading app never opens on an empty grid — it shows whatever
    // was last open, or a sensible default. We have no per-user persistence
    // yet, so default to BTC on MEXC every time; better than a blank screen.
    state.assetType = "crypto";
    state.cryptoExchange = "mexc";
    el("ticker-input").value = "BTC";
    runAnalysis("BTC");
    let relocateTimer = null;
    window.addEventListener("resize", () => {
      resizeAllCharts();
      clearTimeout(relocateTimer);
      relocateTimer = setTimeout(relocateChartSettings, 150);
    });
  });
})();
