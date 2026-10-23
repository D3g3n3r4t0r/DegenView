//! DegenView Native Rust Quant & State-Machine Engine (`libdegenview_rs`).
//!
//! Compiled as a zero-dependency `cdylib` (`cargo build --release`).
//! Called via Python `ctypes.CDLL`, which automatically releases the Python GIL
//! for the entire duration of native execution and enables true multi-core
//! parallelism via `std::thread::scope`.

use std::slice;
use std::thread;

/// Fast state-machine transition kernel for `confirmed_events` in `strategies.py`.
///
/// Signal type codes written to `out_types`:
/// 0 = entry_long, 1 = entry_short, 2 = exit_long, 3 = exit_short,
/// 4 = flip_to_short, 5 = flip_to_long
/// Returns the number of emitted events and writes `final_position` (-1, 0, 1).
#[no_mangle]
pub unsafe extern "C" fn dv_confirmed_events(
    el_ptr: *const u8,
    es_ptr: *const u8,
    xl_ptr: *const u8,
    xs_ptr: *const u8,
    n_total: usize,
    n_confirmed: usize,
    out_indices: *mut usize,
    out_types: *mut u8,
    out_final_pos: *mut i32,
) -> usize {
    if el_ptr.is_null()
        || es_ptr.is_null()
        || xl_ptr.is_null()
        || xs_ptr.is_null()
        || out_indices.is_null()
        || out_types.is_null()
        || out_final_pos.is_null()
    {
        return 0;
    }

    let el = slice::from_raw_parts(el_ptr, n_total);
    let es = slice::from_raw_parts(es_ptr, n_total);
    let xl = slice::from_raw_parts(xl_ptr, n_total);
    let xs = slice::from_raw_parts(xs_ptr, n_total);
    let idx_out = slice::from_raw_parts_mut(out_indices, n_total);
    let typ_out = slice::from_raw_parts_mut(out_types, n_total);

    let mut pos: i32 = 0;
    let mut count: usize = 0;

    for i in 0..n_total {
        let prev_pos = pos;
        if pos == 1 && xl[i] != 0 {
            pos = 0;
        } else if pos == -1 && xs[i] != 0 {
            pos = 0;
        }
        if el[i] != 0 {
            pos = 1;
        } else if es[i] != 0 {
            pos = -1;
        }

        if pos == prev_pos {
            continue;
        }
        if i >= n_confirmed {
            continue;
        }

        let code: u8 = if prev_pos == 0 && pos == 1 {
            0 // entry_long
        } else if prev_pos == 0 && pos == -1 {
            1 // entry_short
        } else if prev_pos == 1 && pos == 0 {
            2 // exit_long
        } else if prev_pos == -1 && pos == 0 {
            3 // exit_short
        } else if prev_pos == 1 && pos == -1 {
            4 // flip_to_short
        } else {
            5 // flip_to_long
        };

        idx_out[count] = i;
        typ_out[count] = code;
        count += 1;
    }

    *out_final_pos = pos;
    count
}

/// Computes Exponential Moving Average (EMA) matching pandas `ewm(span=period, adjust=False).mean()`.
#[no_mangle]
pub unsafe extern "C" fn rust_ema(
    input_ptr: *const f64,
    len: usize,
    period: usize,
    out_ptr: *mut f64,
) -> i32 {
    if input_ptr.is_null() || out_ptr.is_null() || len == 0 || period == 0 {
        return -1;
    }
    let input = slice::from_raw_parts(input_ptr, len);
    let out = slice::from_raw_parts_mut(out_ptr, len);
    ema_slice(input, period, out);
    0
}

fn ema_slice(input: &[f64], period: usize, out: &mut [f64]) {
    let alpha = 2.0 / (period as f64 + 1.0);
    let one_minus_alpha = 1.0 - alpha;
    let mut started = false;
    let mut prev = 0.0_f64;
    for i in 0..input.len() {
        let v = input[i];
        if v.is_nan() {
            out[i] = f64::NAN;
        } else if !started {
            prev = v;
            out[i] = prev;
            started = true;
        } else {
            prev = alpha * v + one_minus_alpha * prev;
            out[i] = prev;
        }
    }
}

/// Computes Batch EMA across `n_periods` in parallel using `std::thread::scope`.
#[no_mangle]
pub unsafe extern "C" fn rust_ema_batch_parallel(
    input_ptr: *const f64,
    len: usize,
    periods_ptr: *const usize,
    n_periods: usize,
    out_ptr: *mut f64,
) -> i32 {
    if input_ptr.is_null() || periods_ptr.is_null() || out_ptr.is_null() || len == 0 || n_periods == 0 {
        return -1;
    }
    let input = slice::from_raw_parts(input_ptr, len);
    let periods = slice::from_raw_parts(periods_ptr, n_periods);
    let out = slice::from_raw_parts_mut(out_ptr, n_periods * len);

    let workers = thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(n_periods);
    let chunk_rows = (n_periods + workers - 1) / workers;

    thread::scope(|s| {
        for (chunk_idx, out_chunk) in out.chunks_mut(chunk_rows * len).enumerate() {
            let start_p = chunk_idx * chunk_rows;
            let end_p = (start_p + chunk_rows).min(n_periods);
            let p_slice = &periods[start_p..end_p];
            s.spawn(move || {
                for (j, &p) in p_slice.iter().enumerate() {
                    let row_out = &mut out_chunk[(j * len)..((j + 1) * len)];
                    ema_slice(input, p, row_out);
                }
            });
        }
    });
    0
}

/// Wilder's RSI (14) + Bollinger Bands (20, 2.0) in a single SIMD-friendly native pass.
#[no_mangle]
pub unsafe extern "C" fn dv_rsi_bollinger(
    close_ptr: *const f64,
    n: usize,
    rsi_len: usize,
    bb_len: usize,
    bb_mult: f64,
    out_rsi: *mut f64,
    out_bb_upper: *mut f64,
    out_bb_lower: *mut f64,
    out_bb_mid: *mut f64,
) {
    if close_ptr.is_null() || n == 0 {
        return;
    }
    let close = slice::from_raw_parts(close_ptr, n);
    let rsi = slice::from_raw_parts_mut(out_rsi, n);
    let upper = slice::from_raw_parts_mut(out_bb_upper, n);
    let lower = slice::from_raw_parts_mut(out_bb_lower, n);
    let mid = slice::from_raw_parts_mut(out_bb_mid, n);

    let alpha = 1.0 / (rsi_len as f64);
    let mut avg_gain = 0.0_f64;
    let mut avg_loss = 0.0_f64;
    rsi[0] = f64::NAN;

    for i in 1..n {
        let diff = close[i] - close[i - 1];
        let gain = if diff > 0.0 { diff } else { 0.0 };
        let loss = if diff < 0.0 { -diff } else { 0.0 };
        if i == 1 {
            avg_gain = gain;
            avg_loss = loss;
        } else {
            avg_gain = alpha * gain + (1.0 - alpha) * avg_gain;
            avg_loss = alpha * loss + (1.0 - alpha) * avg_loss;
        }
        if i < rsi_len {
            rsi[i] = f64::NAN;
        } else if avg_loss == 0.0 {
            rsi[i] = 100.0;
        } else {
            let rs = avg_gain / avg_loss;
            rsi[i] = 100.0 - (100.0 / (1.0 + rs));
        }
    }

    for i in 0..n {
        if i + 1 < bb_len {
            mid[i] = f64::NAN;
            upper[i] = f64::NAN;
            lower[i] = f64::NAN;
        } else {
            let window = &close[(i + 1 - bb_len)..=i];
            let mut sum = 0.0;
            for &v in window {
                sum += v;
            }
            let mean = sum / (bb_len as f64);
            let mut var_sum = 0.0;
            for &v in window {
                let d = v - mean;
                var_sum += d * d;
            }
            let std = (var_sum / (bb_len as f64)).sqrt();
            mid[i] = mean;
            upper[i] = mean + bb_mult * std;
            lower[i] = mean - bb_mult * std;
        }
    }
}
