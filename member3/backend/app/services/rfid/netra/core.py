"""NETRA core - Negative-Evidence Trajectory Association with Risk-controlled
abstention. Copied from the reference implementation in ``claude try/netra.py``
(algorithm unchanged); the gantry simulator and the comparison baselines stay
there with the experiment suite.

Links each RFID tag pass to a camera vehicle track, or to "no visible vehicle"
(missed-vehicle or stationary-tag null), with Sinkhorn confidences. A
confirmation threshold from ``selective_risk_threshold`` bounds the error rate
among CONFIRMED identities (with probability >= 1 - delta, i.i.d. passes).

The backend glue (RFID reports -> reads, camera boxes -> tracks, the shadow
assessment) is in ``adapter.py`` / ``shadow.py``.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.special import expit, logsumexp

P_MIN, P_MAX = 1e-4, 1 - 1e-4
FEATURE_SCALE = 10.0  # metres; keeps the logistic regression well conditioned


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------
@dataclass
class Read:
    tag_id: str
    reader_id: str
    t: float  # reader clock, seconds


def _local_linear_smooth(t, z, half=5):
    """Local constant-velocity (degree-1) fit in a +/-half sample window.
    Unbiased for straight segments; cuts position noise by ~sqrt(2*half+1)."""
    n = len(t)
    out = np.empty_like(z)
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        tt = t[a:b] - t[i]
        if b - a >= 3:
            A = np.stack([np.ones_like(tt), tt], 1)
            coef, *_ = np.linalg.lstsq(A, z[a:b], rcond=None)
            out[i] = coef[0]
        else:
            out[i] = z[i]
    return out


@dataclass
class Track:
    track_id: int
    t: np.ndarray        # camera clock, seconds, increasing
    xy: np.ndarray       # (N, 2) road/world coordinates, metres
    plate: str | None = None
    smooth_half: int = 5  # 0 disables trajectory smoothing

    def __post_init__(self):
        self.t = np.asarray(self.t, float)
        self.xy = np.asarray(self.xy, float)
        self.xy_s = (_local_linear_smooth(self.t, self.xy, self.smooth_half)
                     if self.smooth_half and len(self.t) >= 3 else self.xy)
        if len(self.t) > 1:
            k = np.ones(5) / 5
            sm = np.stack([np.convolve(np.pad(self.xy_s[:, i], 2, mode="edge"), k, "valid")
                           for i in range(2)], 1) if len(self.t) >= 5 else self.xy_s
            v = np.gradient(sm, self.t, axis=0)
        else:
            v = np.zeros_like(self.xy)
        self.speed = np.linalg.norm(v, axis=1)

    def sample(self, ts):
        vis = (ts >= self.t[0]) & (ts <= self.t[-1])
        xy = np.stack([np.interp(ts, self.t, self.xy_s[:, 0]),
                       np.interp(ts, self.t, self.xy_s[:, 1])], 1)
        return vis, xy, np.interp(ts, self.t, self.speed)


@dataclass
class Reader:
    """One RFID antenna/read zone.

    link="rate" (NETRA's model): a continuous-time READ-RATE field
        lambda(x, y, speed) = exp(w . features)   [reads per second]
        P(at least one read in a slot of length dt) = 1 - exp(-lambda * dt)
    i.e. a complementary log-log link. It is slot-size invariant and captures
    the flat-topped per-slot hit profile produced by several inventory rounds
    per slot, which a logistic field cannot represent.

    link="logit": per-event logistic probability (dt ignored). Used only by the
    simulator to generate ground-truth reads per inventory round.
    """
    reader_id: str
    cx: float
    cy: float
    w: np.ndarray        # weights for features() below
    tau: float = 0.0     # reader clock minus camera clock (s)
    link: str = "rate"

    @classmethod
    def nominal(cls, reader_id, cx, cy, sx=6.0, sy=3.0, p_peak=0.5, tau=0.0,
                speed_coef=0.0, link="rate", dt=0.1):
        """Installer's first guess: elliptical Gaussian-shaped footprint whose
        peak per-slot (dt) read probability is p_peak."""
        if link == "rate":
            a = np.log(-np.log(1 - p_peak) / dt)
        else:
            a = np.log(p_peak / (1 - p_peak))
        s2 = FEATURE_SCALE ** 2
        w = np.array([a, 0, 0, -0.5 * s2 / sx ** 2, -0.5 * s2 / sy ** 2, 0,
                      speed_coef * FEATURE_SCALE], float)
        return cls(reader_id, cx, cy, w, tau, link)

    def features(self, xy, speed):
        u = (xy[..., 0] - self.cx) / FEATURE_SCALE
        v = (xy[..., 1] - self.cy) / FEATURE_SCALE
        return np.stack([np.ones_like(u), u, v, u * u, v * v, u * v,
                         speed / FEATURE_SCALE], -1)

    def read_prob(self, xy, speed, dt=0.1):
        f = self.features(xy, speed) @ self.w
        if self.link == "rate":
            p = -np.expm1(-np.exp(np.minimum(f, 30.0)) * dt)
        else:
            p = expit(f)
        return np.clip(p, P_MIN, P_MAX)


@dataclass
class Pass:
    """All reads of one tag during one passage through the read zones."""
    tag_id: str
    raw: list            # [(reader_id, reader_time)]
    t0: float            # camera clock
    t1: float

    @property
    def mid(self):
        return 0.5 * (self.t0 + self.t1)


@dataclass
class Window:
    T0: float
    ts: np.ndarray
    passes: list
    track_ids: list
    vis: np.ndarray      # (J, S)
    xy: np.ndarray       # (J, S, 2)
    sp: np.ndarray       # (J, S)
    lpos: np.ndarray     # (R, J, S) log(p/rho0) * vis
    lmiss: np.ndarray    # (R, J, S) log((1-p)/(1-rho0)) * vis
    decide: list = field(default_factory=list)      # evidence row per decided pass
    decide_src: list = field(default_factory=list)  # the original decided passes


# --------------------------------------------------------------------------
# Core algorithm
# --------------------------------------------------------------------------
def sinkhorn_marginals(lam, null_bias=0.0, iters=100):
    """Soft one-to-one association probabilities from an LLR matrix.

    Augmented square matrix: tags x (tracks + tag-nulls) on top,
    track-nulls x (tracks + dummies) below. Returns (P_tag_track, P_tag_null).
    null_bias may be a scalar or a per-tag vector (phantom-vehicle null).
    """
    nk, nj = lam.shape
    n = nk + nj
    L = np.full((n, n), -np.inf)
    L[:nk, :nj] = lam
    L[np.arange(nk), nj + np.arange(nk)] = np.broadcast_to(null_bias, (nk,))
    L[nk + np.arange(nj), np.arange(nj)] = 0.0
    L[nk:, nj:] = 0.0
    for it in range(iters):
        L = L - logsumexp(L, axis=1, keepdims=True)
        L = L - logsumexp(L, axis=0, keepdims=True)
        if it % 10 == 9 and np.max(np.abs(logsumexp(L, axis=1))) < 1e-6:
            break
    P = np.exp(L)
    return P[:nk, :nj], P[np.arange(nk), nj + np.arange(nk)]


def hungarian_with_null(lam, null_bias=0.0):
    """One-to-one decision; returns list of track column index or None per tag."""
    nk, nj = lam.shape
    C = np.full((nk, nj + nk), 1e9)
    C[:, :nj] = -lam
    C[np.arange(nk), nj + np.arange(nk)] = -np.broadcast_to(null_bias, (nk,))
    rows, cols = linear_sum_assignment(C)
    out = [None] * nk
    for i, j in zip(rows, cols):
        out[i] = int(j) if j < nj else None
    return out


def fit_logistic(X, y, wts, beta0, l2=1.0, iters=50):
    """Weighted logistic regression, damped Newton with backtracking line search.

    The L2 penalty pulls toward the previous field (beta0), not toward zero, so a
    reader with little or ambiguous data cannot jump to a degenerate field.
    """
    beta = beta0.copy()
    d = len(beta)

    def objective(b):
        z = X @ b
        ll = np.sum(wts * (y * z - np.logaddexp(0, z)))
        return ll - 0.5 * l2 * np.sum((b - beta0) ** 2)

    f = objective(beta)
    for _ in range(iters):
        p = expit(X @ beta)
        g = X.T @ (wts * (y - p)) - l2 * (beta - beta0)
        H = (X * (wts * p * (1 - p))[:, None]).T @ X + l2 * np.eye(d)
        step = np.linalg.solve(H, g)
        t = 1.0
        while t > 1e-4:
            cand = beta + t * step
            fc = objective(cand)
            if fc >= f:
                break
            t *= 0.5
        else:
            break
        beta, f_old, f = cand, f, fc
        if abs(f - f_old) < 1e-6 * (1 + abs(f)):
            break
    return beta


def fit_rate_field(X, y, wts, beta0, dt, l2=1.0):
    """Weighted ML fit of a read-rate field (complementary log-log link):
        p = 1 - exp(-exp(X @ beta) * dt)
    with an L2 pull toward the previous field. L-BFGS with analytic gradient:
        d loglik / d eta = (y - p) * mu / p,   mu = exp(eta) * dt.
    """
    from scipy.optimize import minimize

    def nll(b):
        eta = np.minimum(X @ b, 30.0)
        mu = np.exp(eta) * dt
        p = np.clip(-np.expm1(-mu), 1e-12, 1.0)
        ll = np.sum(wts * (y * np.log(p) - (1 - y) * mu))
        g_eta = wts * (y - p) * mu / p
        g = X.T @ g_eta - l2 * (b - beta0)
        return -(ll - 0.5 * l2 * np.sum((b - beta0) ** 2)), -g

    res = minimize(nll, beta0.copy(), jac=True, method="L-BFGS-B",
                   options=dict(maxiter=500))
    return res.x


class NETRA:
    def __init__(self, readers: dict[str, Reader], slot=0.1, rho0=1e-3,
                 pass_gap=20.0, max_pass=30.0, window=20.0, pad=2.0, null_bias=0.0,
                 threshold=0.0, use_negative=True, phantom_null=True,
                 p_undetected=0.05, p_static=0.01, static_null=True,
                 phantom_speeds=np.arange(6.0, 27.0, 2.5),
                 phantom_shifts=np.arange(-0.6, 0.61, 0.15)):
        self.readers = readers
        self.rids = list(readers)
        self.slot, self.rho0 = slot, rho0
        self.pass_gap, self.W, self.pad = pass_gap, window, pad
        # A pass is one transit of the gantry corridor: reads further apart than
        # pass_gap (>= gantry spacing / minimum speed) or a span longer than
        # max_pass (>= corridor length / minimum speed) start a new pass.
        self.max_pass = max_pass
        self.null_bias, self.threshold = null_bias, threshold
        self.use_negative = use_negative
        # Phantom-vehicle null: "the tag is on a vehicle the camera missed".
        # Phantoms are constant-speed vehicles along the road (+x) in each lane
        # (lanes = distinct reader cy). Replace phantom_trajectories() with lane
        # centrelines for curved roads.
        self.phantom_null = phantom_null
        self.log_prior_undetected = np.log(p_undetected / (1 - p_undetected))
        # Stationary-tag null: "the tag is not on a moving vehicle" (roadside or
        # parked tag, reflections). Reads follow a constant rate at each reader.
        self.static_null = static_null
        self.log_prior_static = np.log(p_static / (1 - p_static))
        self.phantom_speeds = np.asarray(phantom_speeds, float)
        self.phantom_shifts = np.asarray(phantom_shifts, float)

    def lanes(self):
        return np.unique(np.round([rd.cy for rd in self.readers.values()], 1))

    def _phantom_profiles(self, xa, horizon=60.0):
        """Per-reader log-ratio profiles of a phantom crossing x = xa at relative
        slot 0, for every (lane, speed). Cached; cumulative sums make the miss
        total over any slot range O(1)."""
        key = (xa, self.use_negative,
               tuple(np.concatenate([rd.w for rd in self.readers.values()])))
        cache = self.__dict__.setdefault("_pcache", {})
        if key in cache:
            return cache[key]
        K = int(np.ceil(horizon / self.slot))
        rel = np.arange(-K, K + 1) * self.slot                        # (T,)
        lanes, speeds = self.lanes(), self.phantom_speeds
        Lg, Vg = np.meshgrid(lanes, speeds, indexing="ij")             # (L, V)
        x = xa + Vg[..., None] * rel                                   # (L, V, T)
        xy = np.stack([x, np.broadcast_to(Lg[..., None], x.shape)], -1)
        sp = np.broadcast_to(Vg[..., None], x.shape)
        gain, cum = [], []
        for rid in self.rids:
            pr = self.readers[rid].read_prob(xy, sp, self.slot)
            lp = np.log(pr / self.rho0)
            lm = np.log((1 - pr) / (1 - self.rho0))
            if self.use_negative:
                gain.append(lp - lm)
                cum.append(np.concatenate([np.zeros(lm.shape[:2] + (1,)),
                                           np.cumsum(lm, -1)], -1))
            else:
                gain.append(lp)
                cum.append(np.zeros(lm.shape[:2] + (lm.shape[2] + 1,)))
        cache[key] = (K, np.stack(gain), np.stack(cum))   # (R, L, V, T), (R, L, V, T+1)
        return cache[key]

    def phantom_llr(self, wd, p, taus=None):
        """log mean_h exp(LLR(tag, phantom h)) over the phantom family
        (lane x speed x crossing-time shift): the marginal likelihood that the
        tag rides on a vehicle the camera did not track.

        Anchor: the gantry (reader cx, rounded) with most reads; phantoms cross
        it at the median corrected read time plus a shift grid.
        """
        by_x = defaultdict(list)
        for rid, tr in p.raw:
            rd = self.readers[rid]
            by_x[round(rd.cx, 0)].append(tr - rd.tau)
        xa = max(by_x, key=lambda k: len(by_x[k]))
        ta = float(np.median(by_x[xa]))
        K, gain, cum = self._phantom_profiles(xa)
        S = len(wd.ts)
        sa = int(np.round((ta - wd.T0) / self.slot - 0.5))       # window slot of the anchor
        shifts = np.unique(np.round(self.phantom_shifts / self.slot).astype(int))
        hits = list(self._hits(wd, p, taus))
        out = []
        for d in shifts:
            # window slot i <-> relative profile index k = i - sa - d
            k_lo = max(-sa - d, -K)
            k_hi = min(S - 1 - sa - d, K)
            lam = (cum[:, :, :, k_hi + 1 + K] - cum[:, :, :, k_lo + K]).sum(0)  # (L, V)
            for r, s in hits:
                k = s - sa - d
                if -K <= k <= K:
                    lam = lam + gain[r, :, :, k + K]
            out.append(lam.ravel())
        lam = np.concatenate(out)
        return float(logsumexp(lam) - np.log(len(lam)))

    def static_llr(self, wd, p, taus=None):
        """Stationary-tag null: per reader a constant per-slot read probability
        q_r (maximum likelihood, q_r = n_r / S) over the window, against the
        rho0 background; BIC penalty 0.5*log(S) per reader that read the tag."""
        S = len(wd.ts)
        counts = defaultdict(int)
        for r, s in self._hits(wd, p, taus):
            counts[r] += 1
        llr = 0.0
        for r, n in counts.items():
            q = min(max(n / S, P_MIN), P_MAX)
            llr += n * np.log(q / self.rho0)
            if self.use_negative:
                llr += (S - n) * np.log((1 - q) / (1 - self.rho0))
            llr -= 0.5 * np.log(S)
        return float(llr)

    def combine_nulls(self, phantom, static):
        """log weight of 'tag not on any visible track' = mixture of the
        missed-vehicle and stationary-tag hypotheses, each with its prior."""
        terms = []
        if phantom is not None:
            terms.append(np.asarray(phantom) + self.log_prior_undetected)
        if static is not None:
            terms.append(np.asarray(static) + self.log_prior_static)
        return np.logaddexp.reduce(np.stack(terms), axis=0) + self.null_bias

    def null_scores(self, wd, taus=None):
        """Per-tag log weight of the null hypotheses."""
        if not (self.phantom_null or self.static_null):
            return np.full(len(wd.passes), float(self.null_bias))
        ph = ([self.phantom_llr(wd, p, taus) for p in wd.passes]
              if self.phantom_null else None)
        st = ([self.static_llr(wd, p, taus) for p in wd.passes]
              if self.static_null else None)
        return self.combine_nulls(ph, st)

    # ---------- passes and windows ----------
    def build_passes(self, reads):
        by_tag = defaultdict(list)
        for r in reads:
            tc = r.t - self.readers[r.reader_id].tau
            by_tag[r.tag_id].append((tc, r.reader_id, r.t))
        passes = []
        for tag, lst in by_tag.items():
            lst.sort()
            cur = [lst[0]]
            for item in lst[1:]:
                if (item[0] - cur[-1][0] > self.pass_gap
                        or item[0] - cur[0][0] > self.max_pass):
                    passes.append(self._mk_pass(tag, cur))
                    cur = [item]
                else:
                    cur.append(item)
            passes.append(self._mk_pass(tag, cur))
        return passes

    @staticmethod
    def _mk_pass(tag, items):
        return Pass(tag, [(rid, tr) for _, rid, tr in items], items[0][0], items[-1][0])

    def windows(self, passes, tracks):
        """Streaming windows of length W, step W/2; each pass decided once."""
        if not passes:
            return
        mids = np.array([p.mid for p in passes])
        t0s = np.array([p.t0 for p in passes])
        t1s = np.array([p.t1 for p in passes])
        W = self.W
        a = mids.min() - W / 4
        while a + W / 4 <= mids.max():
            decide = np.where((mids >= a + W / 4) & (mids < a + 3 * W / 4))[0]
            if len(decide):
                inc = np.where((t1s >= a) & (t0s < a + W))[0]
                inc = sorted(set(inc) | set(decide))
                # One evidence row per TAG: a slow vehicle's reads can split into
                # several passes; scoring them separately would count the tag's
                # own reads at the other gantry as misses and make two rows of
                # one tag compete for the same track.
                merged, order = {}, []
                for i in inc:
                    p = passes[i]
                    if p.tag_id not in merged:
                        merged[p.tag_id] = Pass(p.tag_id, list(p.raw), p.t0, p.t1)
                        order.append(p.tag_id)
                    else:
                        m = merged[p.tag_id]
                        m.raw = m.raw + list(p.raw)
                        m.t0, m.t1 = min(m.t0, p.t0), max(m.t1, p.t1)
                wd = self._build_window([merged[t] for t in order], tracks)
                row = {t: n for n, t in enumerate(order)}
                wd.decide = [row[passes[i].tag_id] for i in decide]
                wd.decide_src = [passes[i] for i in decide]
                yield wd
            a += W / 2

    def _build_window(self, passes, tracks):
        T0 = min(p.t0 for p in passes) - self.pad
        T1 = max(p.t1 for p in passes) + self.pad
        ts = np.arange(T0, T1, self.slot) + self.slot / 2
        cand = [tr for tr in tracks if tr.t[-1] >= T0 and tr.t[0] <= T1]
        J, S, R = len(cand), len(ts), len(self.rids)
        vis = np.zeros((J, S), bool)
        xy = np.zeros((J, S, 2))
        sp = np.zeros((J, S))
        for j, tr in enumerate(cand):
            vis[j], xy[j], sp[j] = tr.sample(ts)
        lpos = np.zeros((R, J, S))
        lmiss = np.zeros((R, J, S))
        for r, rid in enumerate(self.rids):
            if J:
                p = self.readers[rid].read_prob(xy, sp, self.slot)
                lpos[r] = np.log(p / self.rho0) * vis
                lmiss[r] = np.log((1 - p) / (1 - self.rho0)) * vis
        return Window(T0, ts, passes, [tr.track_id for tr in cand],
                      vis, xy, sp, lpos, lmiss)

    def _hits(self, wd, p, taus=None):
        """Unique (reader_index, slot) cells in which the tag was read."""
        S = len(wd.ts)
        cells = set()
        for rid, tr in p.raw:
            tau = (taus or {}).get(rid, self.readers[rid].tau)
            s = int(np.floor((tr - tau - wd.T0) / self.slot))
            if 0 <= s < S:
                cells.add((self.rids.index(rid), s))
        return cells

    # ---------- evidence ----------
    def llr(self, wd, taus=None):
        K, J = len(wd.passes), len(wd.track_ids)
        lam = np.zeros((K, J))
        if J == 0:
            return lam
        if self.use_negative:
            lam += wd.lmiss.sum(axis=(0, 2))[None, :]
        for k, p in enumerate(wd.passes):
            for r, s in self._hits(wd, p, taus):
                if self.use_negative:
                    lam[k] += wd.lpos[r, :, s] - wd.lmiss[r, :, s]
                else:
                    lam[k] += wd.lpos[r, :, s]
        return lam

    # ---------- decisions ----------
    def evidence(self, reads, tracks):
        """Compute every evidence variant once per window so that variants and
        null models can be decoded (and tuned) without recomputation.

        Per window: LLR matrices for read+miss ("full") and positive-only ("pos")
        scoring, and the phantom-null marginal LLR for each, without the prior.
        """
        saved = self.use_negative
        out = []
        for wd in self.windows(self.build_passes(reads), tracks):
            rec = dict(track_ids=wd.track_ids, decide=wd.decide, decide_src=wd.decide_src)
            for variant, neg in (("full", True), ("pos", False)):
                self.use_negative = neg
                rec["lam_" + variant] = self.llr(wd)
                rec["phantom_" + variant] = (np.array([self.phantom_llr(wd, p)
                                                       for p in wd.passes])
                                             if self.phantom_null else None)
                rec["static_" + variant] = (np.array([self.static_llr(wd, p)
                                                      for p in wd.passes])
                                            if self.static_null else None)
            out.append(rec)
        self.use_negative = saved
        return out

    def decode(self, ev, variant=None, null=None, null_bias=None, soft=True):
        """Joint one-to-one decisions from precomputed evidence.

        variant: "full" (read+miss) or "pos" (positive only); default from use_negative.
        null:    "structured" (missed-vehicle + stationary-tag nulls, default),
                 "phantom" (missed-vehicle null only),
                 "static" (stationary-tag null only), or
                 "fixed" (generic unmatched penalty = null_bias).
        """
        variant = variant or ("full" if self.use_negative else "pos")
        null = null or ("structured" if (self.phantom_null and self.static_null)
                        else "phantom" if self.phantom_null
                        else "static" if self.static_null else "fixed")
        bias = self.null_bias if null_bias is None else null_bias
        out = []
        for rec in ev:
            lam = rec["lam_" + variant]
            K, J = lam.shape
            if null == "fixed":
                nb = np.full(K, float(bias))
            else:
                ph = rec["phantom_" + variant] if null in ("structured", "phantom") else None
                st = rec["static_" + variant] if null in ("structured", "static") else None
                nb = self.combine_nulls(ph, st) - self.null_bias + bias
            if J:
                assign = hungarian_with_null(lam, nb)
                if soft:
                    P, Pnull = sinkhorn_marginals(lam, nb)
                else:   # decisions only (tuning); confidences set to 1
                    P, Pnull = np.ones((K, J)), np.ones(K)
            else:
                assign, P, Pnull = [None] * K, np.zeros((K, 0)), np.ones(K)
            for k, p in zip(rec["decide"], rec["decide_src"]):
                j = assign[k]
                if j is None:
                    tid, conf, status = None, float(Pnull[k]), "UNKNOWN"
                else:
                    tid, conf = rec["track_ids"][j], float(P[k, j])
                    status = "CONFIRMED" if conf >= self.threshold else "UNKNOWN"
                out.append(dict(
                    tag_id=p.tag_id, t=p.mid, proposed_track=tid,
                    track_id=tid if status == "CONFIRMED" else None,
                    confidence=conf, status=status, n_reads=len(p.raw)))
        return out

    def run(self, reads, tracks):
        return self.decode(self.evidence(reads, tracks))

    # ---------- self-calibration (EM) ----------
    def self_calibrate(self, reads, tracks, iters=4, tau_range=1.0, tau_step=0.05,
                       min_weight=0.05, update_tau=True, update_fields=True,
                       verbose=False):
        for it in range(iters):
            wins = list(self.windows(self.build_passes(reads), tracks))
            post = []
            for wd in wins:
                lam = self.llr(wd)
                P = (sinkhorn_marginals(lam, self.null_scores(wd))[0]
                     if lam.shape[1] else lam)
                post.append(P)

            # M-step (a): reader clock offsets, grid search per reader.
            # For a pass k and reader r, the expected hit gain of slot s is
            # c[s] = sum_j P[k,j] * (lpos - lmiss)[r,j,s]; a clock offset only moves
            # which slots the reads fall in, so each grid point is a cheap lookup.
            span = tau_range if it == 0 else min(tau_range, 0.3)
            for r, rid in enumerate(self.rids if update_tau else []):
                base = self.readers[rid].tau
                grid = base + np.arange(-span, span + 1e-9, tau_step)
                scores = np.zeros(len(grid))
                for wd, P in zip(wins, post):
                    if P.shape[1] == 0:
                        continue
                    gain = wd.lpos[r] - wd.lmiss[r]            # (J, S)
                    S = gain.shape[1]
                    for k, p in enumerate(wd.passes):
                        if P[k].max() < min_weight:
                            continue
                        times = np.array([tr for rr, tr in p.raw if rr == rid])
                        if len(times) == 0:
                            continue
                        c = P[k] @ gain                          # (S,)
                        slots = np.floor((times[None, :] - grid[:, None] - wd.T0)
                                         / self.slot).astype(int)  # (G, n)
                        for g in range(len(grid)):
                            s = np.unique(slots[g])
                            s = s[(s >= 0) & (s < S)]
                            scores[g] += c[s].sum()
                self.readers[rid].tau = float(grid[int(np.argmax(scores))])

            # M-step (b): read fields by weighted logistic regression
            data = {rid: ([], [], []) for rid in self.rids}
            for wd, P in zip(wins, post) if update_fields else []:
                for k, p in enumerate(wd.passes):
                    hits = self._hits(wd, p)
                    for j in np.where(P[k] > min_weight)[0] if P.shape[1] else []:
                        s_idx = np.where(wd.vis[j])[0]
                        for r, rid in enumerate(self.rids):
                            y = np.zeros(len(s_idx))
                            hit_s = {s for rr, s in hits if rr == r}
                            y[[i for i, s in enumerate(s_idx) if s in hit_s]] = 1
                            X = self.readers[rid].features(wd.xy[j, s_idx], wd.sp[j, s_idx])
                            data[rid][0].append(X)
                            data[rid][1].append(y)
                            data[rid][2].append(np.full(len(s_idx), P[k, j]))
            for rid, (Xs, ys, ws) in data.items():
                if Xs:
                    rd = self.readers[rid]
                    X, y, wt = np.vstack(Xs), np.concatenate(ys), np.concatenate(ws)
                    if rd.link == "rate":
                        rd.w = fit_rate_field(X, y, wt, rd.w, self.slot)
                    else:
                        rd.w = fit_logistic(X, y, wt, rd.w)
            if verbose:
                print(f"  EM iter {it + 1}: tau = " +
                      ", ".join(f"{rid}:{self.readers[rid].tau:+.2f}" for rid in self.rids))
        return self


# --------------------------------------------------------------------------
# Identity confirmation with risk control
# --------------------------------------------------------------------------
def marginal_risk_threshold(conf, wrong, alpha, grid=None):
    """Conformal risk control (Angelopoulos et al.). Bounds the MARGINAL rate
    E[1(accepted and wrong)] <= alpha over all passes. Kept for comparison: it
    does NOT bound the error rate among confirmed identities.
    """
    conf = np.asarray(conf, float)
    wrong = np.asarray(wrong, bool)
    n = len(conf)
    grid = np.linspace(0, 1, 2001) if grid is None else grid
    for lam in grid:
        if (n * np.mean((conf >= lam) & wrong) + 1) / (n + 1) <= alpha:
            return float(lam)
    return float("inf")


def selective_risk_threshold(conf, wrong, alpha, delta=0.1, n_candidates=25):
    """Selection-conditioned risk control (Learn-then-Test with a Bonferroni-
    corrected Clopper-Pearson test; cf. selective guaranteed risk).

    Chooses the LOWEST threshold lam whose upper confidence bound on
        P(wrong | confirmed)  (confirmed = proposed and conf >= lam)
    is <= alpha. Guarantee: with probability >= 1 - delta over the calibration
    set, the error rate among CONFIRMED identities is <= alpha, assuming
    calibration and deployment passes are i.i.d. Returns inf when no candidate
    threshold can be certified (the system then confirms nothing).

    conf: confidence per pass, -inf (or <0) for passes with no proposed track.
    wrong: True when the proposed track is not the true one.
    """
    from scipy.stats import beta as beta_dist
    conf = np.asarray(conf, float)
    wrong = np.asarray(wrong, bool)
    proposed = conf >= 0
    if not proposed.any():
        return float("inf")
    cands = np.unique(np.quantile(conf[proposed], np.linspace(0, 0.95, n_candidates)))
    d = delta / len(cands)
    best = float("inf")
    for lam in cands:
        acc = proposed & (conf >= lam)
        n, k = int(acc.sum()), int((acc & wrong).sum())
        if n == 0:
            continue
        ub = 1.0 if k >= n else float(beta_dist.ppf(1 - d, k + 1, n - k))
        if ub <= alpha:
            best = min(best, float(lam))
    return best


def plate_cross_check(decision, track_plate, registry):
    """registry: tag_id -> registered plate. Disagreement -> CONFLICT, never overwrite."""
    d = dict(decision)
    if d["status"] != "CONFIRMED" or track_plate is None:
        return d
    reg = registry.get(d["tag_id"])
    d["plate_read"], d["plate_registered"] = track_plate, reg
    if reg is not None and reg != track_plate:
        d["status"] = "CONFLICT"
    return d


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score(decisions, truth, thr):
    """accuracy: right track (or correctly none); coverage: share of passes
    confirmed; error: wrong confirmations / all passes; sel_error: wrong
    confirmations / confirmations (what the selective guarantee bounds)."""
    n = len(decisions)
    acc = cov = err = 0
    for d in decisions:
        pred = d["proposed_track"] if (d["proposed_track"] is not None
                                       and d["confidence"] >= thr) else None
        gt = truth[d["tag_id"]]
        acc += pred == gt
        cov += pred is not None
        err += pred is not None and pred != gt
    return dict(n=n, accuracy=acc / n, coverage=cov / n, error=err / n,
                sel_error=err / max(cov, 1), confirmed=cov, wrong=err)


def wrong_flags(decisions, truth):
    return [d["proposed_track"] is not None and d["proposed_track"] != truth[d["tag_id"]]
            for d in decisions]


def conf_vector(decisions):
    """Confidence per pass for risk control; -1 when nothing was proposed."""
    return [d["confidence"] if d["proposed_track"] is not None else -1.0
            for d in decisions]
