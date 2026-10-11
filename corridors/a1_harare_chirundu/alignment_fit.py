"""Fit a horizontal alignment of straights and circular curves to a mapped road centreline.

Method (PI method):
  1. Resample the centreline every 5 m and compute a smoothed heading and curvature.
  2. Stretches where the curvature exceeds 1/3000 m are curve regions; the rest are straights.
     Turns above 110 degrees (hairpins) are split into consecutive compound curves.
  3. A straight line is fitted to each straight; consecutive lines intersect at the PIs.
  4. Each curve's radius is the flattest one that fits the mapped points between its two straights
     almost as well as the best fit (so small kinks in the mapped line do not become tiny radii),
     reduced where neighbouring curves would overlap.
  5. Where the result is more than TOL m from the mapped centreline, curves are split (compound
     curves) or gentle curves are added on the straights, and the fit is repeated.

Coordinates are planar (x = easting, y = northing) in metres.
"""

import math

import numpy as np
import shapely
from scipy import ndimage, optimize

STEP = 5.0                 # resampling interval (m)
SIGMA = 20.0               # heading smoothing (m)
K_CURVE = 1 / 3000         # curvature that starts a curve region (1/m)
MIN_DEFL = math.radians(1.0)    # smaller turns are left as straights
MAX_DEFL = math.radians(110.0)  # larger turns are split into compound curves
MIN_TANGENT_FIT = 40.0     # straights shorter than this take their direction from the heading
TOL = 4.0                  # target fit to the mapped centreline (m)
R_MIN, R_MAX = 10.0, 10000.0   # radii above 10 km are effectively straight
FLATTEN = 0.3              # accept this much extra RMS misfit (m) to use a flatter curve


def _resample(x, y):
    d = np.r_[0, np.cumsum(np.hypot(np.diff(x), np.diff(y)))]
    s = np.arange(0, d[-1], STEP)
    s = np.append(s, d[-1]) if d[-1] - s[-1] > 1e-6 else s
    return s, np.interp(s, d, x), np.interp(s, d, y)


def _runs(mask):
    m = np.r_[0, mask.astype(int), 0]
    return list(zip(np.flatnonzero(np.diff(m) == 1), np.flatnonzero(np.diff(m) == -1) - 1))


class Fitter:
    def __init__(self, x, y):
        self.s, self.x, self.y = _resample(np.asarray(x, float), np.asarray(y, float))
        heading = np.unwrap(np.arctan2(np.gradient(self.y), np.gradient(self.x)))
        self.th = ndimage.gaussian_filter1d(heading, SIGMA / STEP)
        self.k = np.gradient(self.th, self.s)
        self.pts = shapely.points(self.x, self.y)

    # -- segmentation -------------------------------------------------------------------------

    def curve_regions(self, i0, i1, k_curve):
        """Curve regions (start, end index) inside [i0, i1] where |curvature| > k_curve."""
        k = self.k[i0:i1 + 1]
        out = []
        for sign in (1, -1):
            for a, b in _runs(sign * k > k_curve):
                out.append([i0 + a, i0 + b, sign])
        out.sort()
        merged = []
        for r in out:  # join same-direction runs separated by less than 40 m
            if merged and r[2] == merged[-1][2] and (r[0] - merged[-1][1]) * STEP < 40:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return [(a, b) for a, b, _ in merged if abs(self.th[b] - self.th[a]) >= MIN_DEFL and b > a]

    def split_large(self, regions):
        out = []
        for a, b in regions:
            defl = abs(self.th[b] - self.th[a])
            parts = max(1, math.ceil(defl / MAX_DEFL))
            if parts == 1:
                out.append((a, b))
                continue
            targets = np.linspace(self.th[a], self.th[b], parts + 1)[1:-1]
            seg = self.th[a:b + 1]
            cuts = [a + int(np.argmin(np.abs(seg - t))) for t in targets]
            bounds = [a] + cuts + [b]
            out += [(p, q) for p, q in zip(bounds[:-1], bounds[1:]) if q > p]
        return out

    # -- geometry -------------------------------------------------------------------------------

    def tangent_line(self, a, b):
        """Point and unit direction of the straight between indices a and b (a <= b)."""
        if (self.s[b] - self.s[a]) >= MIN_TANGENT_FIT:
            trim = int(10 / STEP)
            sl = slice(a + trim, b - trim + 1)
            px, py = self.x[sl], self.y[sl]
            c = np.array([px.mean(), py.mean()])
            u = np.linalg.svd(np.c_[px - c[0], py - c[1]], full_matrices=False)[2][0]
            h = np.array([math.cos(self.th[(a + b) // 2]), math.sin(self.th[(a + b) // 2])])
            return c, (u if u @ h > 0 else -u)
        m = (a + b) // 2
        return np.array([self.x[m], self.y[m]]), np.array([math.cos(self.th[m]), math.sin(self.th[m])])

    @staticmethod
    def intersect(p1, u1, p2, u2):
        den = u1[0] * u2[1] - u1[1] * u2[0]
        if abs(den) < 1e-12:
            return None
        t = ((p2[0] - p1[0]) * u2[1] - (p2[1] - p1[1]) * u2[0]) / den
        return p1 + t * u1

    @staticmethod
    def curve_points(pi, u_in, u_out, R):
        delta = math.atan2(u_in[0] * u_out[1] - u_in[1] * u_out[0], u_in @ u_out)
        T = R * math.tan(abs(delta) / 2)
        tc, ct = pi - T * u_in, pi + T * u_out
        normal = np.array([-u_in[1], u_in[0]]) * (1 if delta > 0 else -1)
        return tc, ct, tc + R * normal, delta, T

    def composite_distance(self, idx, pi, u_in, u_out, R):
        tc, ct, c, delta, _ = self.curve_points(pi, u_in, u_out, R)
        q = np.c_[self.x[idx], self.y[idx]]
        t_in = (q - tc) @ u_in
        t_out = (q - ct) @ u_out
        d_in = np.abs((q - tc) @ np.array([-u_in[1], u_in[0]]))
        d_out = np.abs((q - ct) @ np.array([-u_out[1], u_out[0]]))
        d_arc = np.abs(np.hypot(q[:, 0] - c[0], q[:, 1] - c[1]) - R)
        return np.where(t_in <= 0, d_in, np.where(t_out >= 0, d_out, d_arc))

    def build(self, regions):
        """Lines between regions, PIs, fitted radii; returns element list and curve records."""
        n = len(self.s) - 1
        bounds = [(0, regions[0][0])] if regions else [(0, n)]
        for (a0, b0), (a1, b1) in zip(regions[:-1], regions[1:]):
            bounds.append((b0, a1))
        if regions:
            bounds.append((regions[-1][1], n))
        lines = [self.tangent_line(a, b) for a, b in bounds]

        curves = []
        for k, (a, b) in enumerate(regions):
            (p1, u1), (p2, u2) = lines[k], lines[k + 1]
            pi = self.intersect(p1, u1, p2, u2)
            delta = math.atan2(u1[0] * u2[1] - u1[1] * u2[0], u1 @ u2)
            mid = np.array([self.x[(a + b) // 2], self.y[(a + b) // 2]])
            if pi is None or abs(delta) < math.radians(0.2) or np.hypot(*(pi - mid)) > 20 * (self.s[b] - self.s[a]) + 500:
                curves.append(None)
                continue
            pad = int(20 / STEP)
            idx = np.arange(max(a - pad, 0), min(b + pad, n) + 1)
            def rms(lr):
                return math.sqrt(np.mean(self.composite_distance(idx, pi, u1, u2, math.exp(lr)) ** 2))
            res = optimize.minimize_scalar(rms, bounds=(math.log(R_MIN), math.log(R_MAX)), method="bounded",
                                           options={"xatol": 1e-3})
            lo, hi = res.x, math.log(R_MAX)
            if rms(hi) <= res.fun + FLATTEN:
                lo = hi
            else:
                for _ in range(30):  # largest radius whose RMS is within FLATTEN of the best
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if rms(mid) <= res.fun + FLATTEN else (lo, mid)
            curves.append({"pi": pi, "u_in": u1, "u_out": u2, "delta": delta, "R": math.exp(lo),
                           "region": k})
        return lines, curves

    def assemble(self, lines, curves):
        """Resolve overlaps and produce the element list (lines and arcs) from start to end."""
        start = np.array([self.x[0], self.y[0]])
        end = np.array([self.x[-1], self.y[-1]])
        p0, u0 = lines[0]
        start = p0 + ((start - p0) @ u0) * u0
        pl, ul = lines[-1]
        end = pl + ((end - pl) @ ul) * ul
        cv = [c for c in curves if c is not None]
        dropped = {k for k, c in enumerate(curves) if c is None}
        # Drop curves whose PIs run backwards along the road.
        anchors = [start] + [c["pi"] for c in cv] + [end]
        keep = []
        for i, c in enumerate(cv):
            before, after = anchors[i], anchors[i + 2]
            if (c["pi"] - before) @ c["u_in"] > 0 and (after - c["pi"]) @ c["u_out"] > 0:
                keep.append(c)
            else:
                dropped.add(c["region"])
        if dropped:
            return None, dropped
        cv = keep
        # Shrink radii where tangent lengths overlap.
        for _ in range(4):
            for i, c in enumerate(cv):
                c["T"] = c["R"] * math.tan(abs(c["delta"]) / 2)
            pts = [start] + [c["pi"] for c in cv] + [end]
            for i in range(len(cv) + 1):
                avail = np.hypot(*(pts[i + 1] - pts[i]))
                t_prev = cv[i - 1]["T"] if i > 0 else 0.0
                t_next = cv[i]["T"] if i < len(cv) else 0.0
                if t_prev + t_next > avail and t_prev + t_next > 0:
                    f = avail / (t_prev + t_next)  # curves then meet exactly (compound or reverse)
                    if i > 0:
                        cv[i - 1]["R"] *= f
                        cv[i - 1]["T"] *= f
                    if i < len(cv):
                        cv[i]["R"] *= f
                        cv[i]["T"] *= f
        elements, pos = [], start
        for c in cv:
            tc, ct, centre, delta, T = self.curve_points(c["pi"], c["u_in"], c["u_out"], c["R"])
            if np.hypot(*(tc - pos)) > 1e-3:
                elements.append({"type": "line", "start": pos, "end": tc})
            elements.append({"type": "curve", "start": tc, "end": ct, "centre": centre, "R": c["R"],
                             "delta": delta, "pi": c["pi"], "T": T})
            pos = ct
        if np.hypot(*(end - pos)) > 1e-3:
            elements.append({"type": "line", "start": pos, "end": end})
        sta = 0.0
        for el in elements:
            el["sta"] = sta
            el["length"] = (abs(el["delta"]) * el["R"] if el["type"] == "curve"
                            else float(np.hypot(*(el["end"] - el["start"]))))
            sta += el["length"]
        return elements, set()

    def solve(self, regions):
        """Build the alignment, removing curves that cannot be set out until all fit together."""
        while True:
            lines, curves = self.build(regions)
            elements, dropped = self.assemble(lines, curves)
            if elements is not None:
                return regions, elements
            regions = [r for k, r in enumerate(regions) if k not in dropped]

    @staticmethod
    def polyline(elements, max_step=1.0):
        coords = [tuple(elements[0]["start"])]
        for el in elements:
            if el["type"] == "line":
                coords.append(tuple(el["end"]))
                continue
            c, R, delta = el["centre"], el["R"], el["delta"]
            a0 = math.atan2(el["start"][1] - c[1], el["start"][0] - c[0])
            n = max(2, int(math.ceil(abs(delta) * R / max_step)))
            for t in np.linspace(0, delta, n + 1)[1:]:
                coords.append((c[0] + R * math.cos(a0 + t), c[1] + R * math.sin(a0 + t)))
        return shapely.LineString(coords)

    def deviation(self, elements):
        coords = np.asarray(self.polyline(elements).coords)
        segs = shapely.linestrings(np.stack([coords[:-1], coords[1:]], axis=1))
        tree = shapely.STRtree(segs)
        (_, j), dist = tree.query_nearest(self.pts, return_distance=True, all_matches=False)
        return dist

    # -- driver ---------------------------------------------------------------------------------

    def fit(self, rounds=5):
        n = len(self.s) - 1
        regions = self.split_large(self.curve_regions(0, n, K_CURVE))
        for _ in range(rounds):
            regions, elements = self.solve(regions)
            dev = self.deviation(elements)
            new, changed = [], False
            bounds = [(0, regions[0][0])] + [(b0, a1) for (_, b0), (a1, _) in zip(regions[:-1], regions[1:])] \
                + [(regions[-1][1], n)] if regions else [(0, n)]
            for k, (a, b) in enumerate(regions):
                # gentle curves hidden in the straight before this curve
                ta, tb = bounds[k]
                if tb - ta > 4 and dev[ta:tb + 1].max() > TOL:
                    extra = self.curve_regions(ta + 1, tb - 1, K_CURVE / 4)
                    if extra:
                        new += self.split_large(extra)
                        changed = True
                if dev[a:b + 1].max() > TOL and (b - a) * STEP >= 60:
                    m = a + int(np.argmin(np.abs(self.th[a:b + 1] - (self.th[a] + self.th[b]) / 2)))
                    m = min(max(m, a + 2), b - 2)
                    new += [(a, m), (m, b)]
                    changed = True
                else:
                    new.append((a, b))
            ta, tb = bounds[-1]
            if tb - ta > 4 and dev[ta:tb + 1].max() > TOL:
                extra = self.curve_regions(ta + 1, tb - 1, K_CURVE / 4)
                if extra:
                    new += self.split_large(extra)
                    changed = True
            regions = sorted(set(new))
            if not changed:
                break
        regions, elements = self.solve(regions)
        return elements, self.deviation(elements)


def fit_alignment(x, y):
    """Returns (elements, deviation per 5 m sample, fitter)."""
    f = Fitter(x, y)
    elements, dev = f.fit()
    return elements, dev, f
