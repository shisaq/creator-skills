"""Beat / onset analysis in plain numpy (no librosa).

onset envelope: log band-energy spectral flux
tempo:          autocorrelation with a log-normal prior around 110 BPM
beats:          dynamic-programming tracker (Ellis 2007)
downbeats:      the beat phase (of `meter`) with the most low-frequency onset energy
onsets:         adaptive peak picking, for free-tempo (rubato) playing
music regions:  where the sound is loud enough to be music rather than silence
"""

from __future__ import annotations

import numpy as np

SR = 22050
HOP = 512
NFFT = 2048
FR = SR / HOP  # envelope frames per second


def _bands(sr: int, nfft: int, n: int = 48, lo: float = 30.0, hi: float = 8000.0):
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    edges = np.geomspace(lo, hi, n + 1)
    idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(n)]
    return [ix if len(ix) else np.array([np.argmin(np.abs(freqs - edges[i]))]) for i, ix in enumerate(idx)], edges


def _envelopes(y: np.ndarray):
    n_frames = 1 + max(0, (len(y) - NFFT) // HOP)
    win = np.hanning(NFFT).astype(np.float32)
    bands, edges = _bands(SR, NFFT)
    low_bands = [i for i in range(len(bands)) if edges[i + 1] <= 250]
    E = np.zeros((n_frames, len(bands)), np.float32)
    rms = np.zeros(n_frames, np.float32)
    chunk = 2048
    for s in range(0, n_frames, chunk):
        e = min(n_frames, s + chunk)
        idx = (np.arange(s, e)[:, None] * HOP) + np.arange(NFFT)[None, :]
        fr = y[idx] * win
        rms[s:e] = np.sqrt((y[idx] ** 2).mean(axis=1))
        mag = np.abs(np.fft.rfft(fr, axis=1)) ** 2
        for b, ix in enumerate(bands):
            E[s:e, b] = mag[:, ix].mean(axis=1)
    L = np.log1p(1000.0 * E / (E.max() + 1e-12))
    d = np.maximum(0.0, np.diff(L, axis=0, prepend=L[:1]))
    flux = d.sum(axis=1)
    low = d[:, low_bands].sum(axis=1) if low_bands else flux
    return flux, low, rms


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    k = np.ones(n) / n
    return np.convolve(x, k, mode="same")


def _normalize_env(flux: np.ndarray) -> np.ndarray:
    o = flux - _smooth(flux, FR * 0.5)
    o = np.maximum(0.0, o)
    sd = o.std() + 1e-9
    return o / sd


def _tempo(onset: np.ndarray, lo_bpm=50, hi_bpm=200, center=110.0):
    o = onset - onset.mean()
    n = len(o)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfft(o, size)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    ac = ac / (ac[0] + 1e-9)
    lags = np.arange(int(60 * FR / hi_bpm), min(n - 1, int(60 * FR / lo_bpm)) + 1)
    if len(lags) < 3:
        return 100.0, 0.0
    bpm = 60 * FR / lags
    prior = np.exp(-0.5 * (np.log2(bpm / center) / 0.9) ** 2)
    score = ac[lags] * prior
    i = int(np.argmax(score))
    # parabolic refinement of the lag
    if 0 < i < len(lags) - 1:
        a, b, c = ac[lags[i - 1]], ac[lags[i]], ac[lags[i + 1]]
        den = a - 2 * b + c
        shift = 0.5 * (a - c) / den if den != 0 else 0.0
        lag = lags[i] + float(np.clip(shift, -0.5, 0.5))
    else:
        lag = float(lags[i])
    return 60 * FR / lag, float(ac[lags[i]])


def _track(onset: np.ndarray, bpm: float, tightness: float = 100.0) -> np.ndarray:
    period = 60 * FR / bpm
    w = np.arange(-int(period), int(period) + 1)
    local = np.convolve(onset, np.exp(-0.5 * (w * 32.0 / period) ** 2), mode="same")
    n = len(local)
    cum = np.zeros(n)
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(2 * period)), max(1, int(round(period / 2)))
    offsets = np.arange(-lo, -hi + 1)
    txwt = -tightness * np.log(-offsets / period) ** 2
    for i in range(n):
        s, e = i - lo, i - hi + 1
        if e <= 0:
            cum[i] = local[i]
            continue
        a = max(0, s)
        cand = cum[a:e] + txwt[a - s:]
        j = int(np.argmax(cand))
        cum[i] = local[i] + cand[j]
        back[i] = a + j
    # last beat: last local max of cum above half the median of local maxima
    mx = np.where((cum[1:-1] > cum[:-2]) & (cum[1:-1] >= cum[2:]))[0] + 1
    if len(mx) == 0:
        return np.array([], dtype=int)
    thr = 0.5 * np.median(cum[mx])
    last = int(mx[cum[mx] >= thr][-1])
    beats = [last]
    while back[beats[-1]] >= 0:
        beats.append(int(back[beats[-1]]))
    return np.array(beats[::-1])


def _peaks(onset: np.ndarray, min_gap_s=0.1):
    n = len(onset)
    w = max(1, int(0.035 * FR))
    thr = _smooth(onset, FR * 0.6) + 0.6 * onset.std()
    out = []
    last = -10**9
    gap = int(min_gap_s * FR)
    for i in range(w, n - w):
        v = onset[i]
        if v >= thr[i] and v == onset[i - w:i + w + 1].max() and i - last >= gap:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def _regions(rms: np.ndarray, min_len=3.0, merge_gap=2.0):
    db = 20 * np.log10(_smooth(rms, FR * 1.0) + 1e-9)
    ref = np.percentile(db, 95)
    on = db > ref - 30
    regs = []
    i, n = 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            regs.append([i / FR, j / FR])
            i = j
        else:
            i += 1
    merged = []
    for r in regs:
        if merged and r[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [[round(a, 2), round(b, 2)] for a, b in merged if b - a >= min_len]


def analyze(y: np.ndarray, meter: int = 4) -> dict:
    if len(y) < SR * 2:
        raise SystemExit("音频太短（不到 2 秒），没法分析节拍。")
    flux, low, rms = _envelopes(y)
    onset = _normalize_env(flux)
    low_on = _normalize_env(low)
    bpm, clarity = _tempo(onset)
    beats_f = _track(onset, bpm)
    music = _regions(rms)

    def in_music(t):
        return any(a - 0.3 <= t <= b + 0.3 for a, b in music)

    beats_f = np.array([b for b in beats_f if in_music(b / FR)], dtype=int)
    peaks = _peaks(onset)
    # how many tracked beats sit on a real note attack (steady music: most of them; rubato: few)
    tol = int(0.07 * FR)
    if len(beats_f) and len(peaks):
        near = np.array([np.min(np.abs(peaks - b)) <= tol for b in beats_f])
        agreement = float(near.mean())
    else:
        agreement = 0.0

    def strength(env, f):
        a, b = max(0, f - 2), min(len(env), f + 3)
        return float(env[a:b].max()) if b > a else 0.0

    # downbeats: phase with the most bass-onset energy
    down = []
    if len(beats_f) >= meter * 2:
        scores = [np.mean([strength(low_on, b) + 0.5 * strength(onset, b) for b in beats_f[p::meter]]) for p in range(meter)]
        ph = int(np.argmax(scores))
        down = beats_f[ph::meter]
    energy_env = rms / (np.percentile(rms, 98) + 1e-9)
    pk_strength = np.array([strength(onset, p) for p in peaks]) if len(peaks) else np.array([])
    if len(pk_strength):
        pk_strength = np.clip(pk_strength / (np.percentile(pk_strength, 95) + 1e-9), 0, 1)
    steady = agreement >= 0.55 and clarity >= 0.15
    advice = ("节拍稳定：律动效果跟着拍子走（sync=beats）。" if steady else
              "节拍不稳（自由速度/散板，或打击感弱）：律动效果改成跟着音符起音走（sync=onsets）。")
    return {
        "bpm": round(bpm, 1),
        "meter": meter,
        "clarity": round(clarity, 3),
        "agreement": round(agreement, 3),
        "steady": bool(steady),
        "advice": advice,
        "music": music,
        "beats": [round(b / FR, 3) for b in beats_f],
        "downbeats": [round(b / FR, 3) for b in down],
        "onsets": [[round(p / FR, 3), round(float(s), 3)] for p, s in zip(peaks, pk_strength)],
        "energy_fps": round(FR / 4, 3),
        "energy": [round(float(v), 3) for v in np.clip(energy_env[::4], 0, 1.5)],
    }
