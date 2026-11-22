"""What effects need to know about the music. Every effect (built-in or your own) gets it as ctx.music.

  music.bpm, music.steady, music.regions          tempo, beat reliability, where music plays
  music.hits(kind, sync, lo, hi)                   [(time, strength 0..1)] to trigger things on
       kind="beat"  every beat (downbeats 1.0, others 0.55)
       kind="down"  downbeats only (the "1" of each bar)
       kind="note"  note attacks (works for free-tempo playing)
       kind="big"   downbeats when steady, else the strongest note attacks
       sync="auto"  steady music → beats, free tempo → notes (recommended)
  music.envelope(t, hits, decay=0.22)              0..1, jumps on each hit then decays — the "pulse" curve
  music.energy(t)                                   0..1 loudness around t (verse quiet, chorus loud)
  music.last_hit(t, hits) -> (time, strength)|None  the most recent hit at or before t
"""

from __future__ import annotations

import bisect
import math


class Music:
    def __init__(self, b: dict | None, duration: float):
        b = b or {}
        self.raw = b
        self.duration = duration
        self.bpm = b.get("bpm")
        self.steady = bool(b.get("steady"))
        self.regions = b.get("music") or []
        self.beats = b.get("beats") or []
        self.downbeats = b.get("downbeats") or []
        self.onsets = b.get("onsets") or []
        self._e = b.get("energy") or []
        self._efps = b.get("energy_fps") or 10

    def span(self, lo=None, hi=None):
        lo = float(lo) if lo is not None else (self.regions[0][0] if self.regions else 0.0)
        hi = float(hi) if hi is not None else (self.regions[-1][1] if self.regions else self.duration)
        return lo, min(hi, self.duration)

    def hits(self, kind="beat", sync="auto", lo=None, hi=None):
        lo, hi = self.span(lo, hi)
        use_beats = (sync == "beats") or (sync == "auto" and self.steady)
        down = set(round(x, 3) for x in self.downbeats)
        out = []
        if kind == "note" or not use_beats:
            gap, thr = ((0.12, 0.25) if kind in ("beat", "note") else (0.35, 0.6))
            last = -9.0
            for t, s in self.onsets:
                if s >= thr and t - last >= gap:
                    out.append((t, max(0.0, min(1.0, 0.35 + 0.65 * s))))
                    last = t
        elif kind in ("down", "big"):
            out = [(t, 1.0) for t in self.downbeats]
        else:
            out = [(t, 1.0 if round(t, 3) in down else 0.55) for t in self.beats]
        return [(t, s) for t, s in out if lo <= t <= hi]

    @staticmethod
    def last_hit(t, hits):
        i = bisect.bisect_right([h[0] for h in hits], t) if hits else 0
        return hits[i - 1] if i else None

    def envelope(self, t, hits, decay=0.22, attack=0.03):
        if not hits:
            return 0.0
        times = getattr(self, "_cache_times", None)
        if times is None or getattr(self, "_cache_id", None) is not id(hits):
            self._cache_times, self._cache_id = [h[0] for h in hits], id(hits)
            times = self._cache_times
        i = bisect.bisect_right(times, t)
        v = 0.0
        for j in range(max(0, i - 6), i):
            tj, sj = hits[j]
            v = max(v, sj * math.exp(-(t - tj) / decay))
        if i < len(hits) and hits[i][0] - t < attack:
            v = max(v, hits[i][1] * (1 - (hits[i][0] - t) / attack))
        return min(1.0, v)

    def energy(self, t):
        if not self._e:
            return 1.0
        i = int(t * self._efps)
        return max(0.0, min(1.0, float(self._e[min(len(self._e) - 1, max(0, i))])))

    def sections(self, win=8.0):
        """Coarse loudness map: [(start, end, '安静'|'中'|'强')] — to plan where effects hold back or open up."""
        if not self._e:
            return []
        lo, hi = self.span()
        out = []
        t = lo
        vals = []
        while t < hi:
            e = min(hi, t + win)
            seg = self._e[int(t * self._efps): max(int(t * self._efps) + 1, int(e * self._efps))]
            vals.append((t, e, sum(seg) / max(1, len(seg))))
            t = e
        if not vals:
            return []
        srt = sorted(v for _, _, v in vals)
        q1, q2 = srt[len(srt) // 3], srt[2 * len(srt) // 3]
        for s, e, v in vals:
            lab = "强" if v >= q2 and v > 0.45 else ("安静" if v <= q1 or v < 0.25 else "中")
            if out and out[-1][2] == lab:
                out[-1] = (out[-1][0], e, lab)
            else:
                out.append((s, e, lab))
        return out
