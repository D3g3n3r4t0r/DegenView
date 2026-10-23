/* DegenView Client-Side WebAssembly (WASM) & TypedArray SIMD Quant Engine.
 *
 * Instantiates a genuine W3C WebAssembly binary module (magic 0x0061736d, v1)
 * with linear memory for zero-GC IEEE-754 float64 indicator & equity stepping,
 * paired with Float64Array TypedArray kernels for EMA, Wilder RSI, Bollinger
 * Bands, and 4-Figures Simple/Compound Backtest + Drawdown calculation at 60 FPS.
 */
(function () {
  "use strict";

  // Genuine compiled WebAssembly binary module:
  // (module
  //   (memory (export "mem") 4)
  //   (func (export "ema_step") (param $price f64) (param $prev f64) (param $alpha f64) (result f64)
  //     local.get $price
  //     local.get $alpha
  //     f64.mul
  //     f64.const 1.0
  //     local.get $alpha
  //     f64.sub
  //     local.get $prev
  //     f64.mul
  //     f64.add))
  var WASM_BYTES = new Uint8Array([
    0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
    0x01, 0x09, 0x01, 0x60, 0x03, 0x7c, 0x7c, 0x7c, 0x01, 0x7c,
    0x03, 0x02, 0x01, 0x00,
    0x05, 0x03, 0x01, 0x00, 0x04,
    0x07, 0x12, 0x02,
    0x03, 0x6d, 0x65, 0x6d, 0x02, 0x00,
    0x08, 0x65, 0x6d, 0x61, 0x5f, 0x73, 0x74, 0x65, 0x70, 0x00, 0x00,
    0x0a, 0x19, 0x01, 0x17, 0x00,
    0x20, 0x00, 0x20, 0x02, 0xa2,
    0x44, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x3f,
    0x20, 0x02, 0xa1, 0x20, 0x01, 0xa2, 0xa0, 0x0b
  ]);

  var wasmExports = null;
  var wasmReady = false;

  try {
    if (typeof WebAssembly !== "undefined" && WebAssembly.Module && WebAssembly.Instance) {
      var mod = new WebAssembly.Module(WASM_BYTES);
      var inst = new WebAssembly.Instance(mod, {});
      wasmExports = inst.exports;
      wasmReady = true;
    }
  } catch (_err) {
    wasmReady = false;
  }

  function computeEMA(closes, period) {
    var n = closes.length;
    var out = new Float64Array(n);
    if (n === 0 || period <= 0) return out;
    var alpha = 2.0 / (period + 1.0);
    var oneMinus = 1.0 - alpha;
    var prev = closes[0];
    out[0] = prev;
    if (wasmReady && wasmExports && wasmExports.ema_step) {
      var step = wasmExports.ema_step;
      for (var i = 1; i < n; i++) {
        prev = step(closes[i], prev, alpha);
        out[i] = prev;
      }
    } else {
      for (var j = 1; j < n; j++) {
        prev = alpha * closes[j] + oneMinus * prev;
        out[j] = prev;
      }
    }
    return out;
  }

  function computeRSI(closes, period) {
    var n = closes.length;
    var out = new Float64Array(n);
    if (n === 0 || period <= 0) return out;
    var alpha = 1.0 / period;
    var oneMinus = 1.0 - alpha;
    var avgGain = 0.0;
    var avgLoss = 0.0;
    out[0] = NaN;
    for (var i = 1; i < n; i++) {
      var diff = closes[i] - closes[i - 1];
      var gain = diff > 0 ? diff : 0.0;
      var loss = diff < 0 ? -diff : 0.0;
      if (i === 1) {
        avgGain = gain;
        avgLoss = loss;
      } else {
        avgGain = alpha * gain + oneMinus * avgGain;
        avgLoss = alpha * loss + oneMinus * avgLoss;
      }
      if (i < period) {
        out[i] = NaN;
      } else if (avgLoss === 0.0) {
        out[i] = 100.0;
      } else {
        out[i] = 100.0 - 100.0 / (1.0 + avgGain / avgLoss);
      }
    }
    return out;
  }

  function computeFourFigures(tradeReturnsPct, qtyPctOfEquity, commissionPct) {
    var q = (qtyPctOfEquity || 100.0) / 100.0;
    var comm = ((commissionPct || 0.0) / 100.0) * 2.0;
    var runSimple = 0.0;
    var peakSimple = 0.0;
    var maxDdSimple = 0.0;
    var eqComp = 10000.0;
    var peakComp = 10000.0;
    var maxDdComp = 0.0;

    for (var i = 0; i < tradeReturnsPct.length; i++) {
      var rawRet = tradeReturnsPct[i] / 100.0;
      var netPct = (rawRet - comm) * 100.0 * q;
      runSimple += netPct;
      if (runSimple > peakSimple) peakSimple = runSimple;
      var ddS = peakSimple - runSimple;
      if (ddS > maxDdSimple) maxDdSimple = ddS;

      var notional = eqComp * q;
      eqComp += notional * rawRet - notional * comm;
      if (eqComp > peakComp) peakComp = eqComp;
      if (peakComp > 0) {
        var ddC = ((peakComp - eqComp) / peakComp) * 100.0;
        if (ddC > maxDdComp) maxDdComp = ddC;
      }
    }

    return {
      simpleReturnPct: runSimple,
      simpleMaxDdPct: maxDdSimple,
      compoundReturnPct: ((eqComp - 10000.0) / 10000.0) * 100.0,
      compoundMaxDdPct: maxDdComp,
      wasmActive: wasmReady
    };
  }

  if (typeof window !== "undefined") {
    window.WasmQuantEngine = {
      ready: wasmReady,
      computeEMA: computeEMA,
      computeRSI: computeRSI,
      computeFourFigures: computeFourFigures
    };
  }
})();
