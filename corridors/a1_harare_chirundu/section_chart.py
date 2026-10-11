"""Chart and summarise one stretch of the A1 profile from the Excel output of build_a1_corridor.py.

Usage:
    python section_chart.py A1_Harare_Chirundu_profile_and_steep_sections.xlsx 290 315 out.png
"""

import sys

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SENSITIVE = 5.0  # m, matches build_a1_corridor.py


def main(xlsx, km_from, km_to, out):
    sheets = pd.read_excel(xlsx, sheet_name=None)
    profile = next(v for k, v in sheets.items() if k.startswith("Profile every"))
    a, b = km_from * 1000, km_to * 1000
    s = profile[(profile["Chainage (m)"] >= a) & (profile["Chainage (m)"] <= b)]
    ch = s["Chainage (m)"].to_numpy() / 1000
    z = s["Elevation corrected (m)"].to_numpy()
    raw = s["Copernicus raw (m)"].to_numpy()
    srtm = s["SRTM raw (m)"].to_numpy()
    g = s[next(c for c in s.columns if c.startswith("Gradient over"))].to_numpy()
    sens = s[next(c for c in s.columns if c.startswith("Height change"))].to_numpy()
    step = np.median(np.diff(ch))

    print(f"km {km_from}-{km_to}: {z[0]:.0f} m -> {z[-1]:.0f} m, overall {(z[-1] - z[0]) / (b - a) * 100:+.1f}%")
    print(f"steepest downhill {g.min():.1f}% at km {ch[np.argmin(g)]:.2f}, uphill {g.max():.1f}% at km {ch[np.argmax(g)]:.2f}")
    for lo, hi, label in [(0, 4, "0-4%"), (4, 6, "4-6%"), (6, 8, "6-8%"), (8, 99, ">8%")]:
        print(f"  {label}: {((np.abs(g) >= lo) & (np.abs(g) < hi)).sum() * step:.1f} km")
    print(f"largest step between stations: {np.abs(np.diff(z)).max():.1f} m (raw DEM {np.abs(np.diff(raw)).max():.1f} m)")

    steep = sheets["Steep sections"]
    steep = steep[(steep["To (m)"] >= a) & (steep["From (m)"] <= b)]
    fig, (ax, axg) = plt.subplots(2, 1, figsize=(15, 8), dpi=130, gridspec_kw={"height_ratios": [4, 1]},
                                  sharex=True)
    m = np.r_[0, (sens > SENSITIVE).astype(int), 0]
    for lo, hi in zip(np.flatnonzero(np.diff(m) == 1), np.flatnonzero(np.diff(m) == -1) - 1):
        ax.axvspan(ch[lo], ch[hi], color="#b4409c", alpha=0.12, lw=0)
    ax.plot(ch, raw, color="#d62728", lw=0.7, label="Raw Copernicus DEM")
    ax.plot(ch, srtm, color="#888", lw=0.7, label="Raw SRTM")
    ax.plot(ch, z, color="black", lw=1.4, label="Corrected profile")
    for _, r in steep.iterrows():
        mid = (r["From (m)"] + r["To (m)"]) / 2000
        if r["Length (m)"] >= 300 and km_from <= mid <= km_to:
            ax.annotate(f"{r['Average grade (%)']:+.1f}% avg\nmax {r['Max grade (%)']:.0f}%",
                        (mid, np.interp(mid, ch, z)), xytext=(18, 18), textcoords="offset points", fontsize=8,
                        arrowprops={"arrowstyle": "-", "color": "#999"})
    ax.set_ylabel("Elevation (m)")
    ax.grid(alpha=0.3)
    ax.legend(handles=ax.get_legend_handles_labels()[0] + [
        Patch(color="#b4409c", alpha=0.25, label=f"Height changes >{SENSITIVE:.0f} m if centreline 30 m off")],
        fontsize=8, loc="upper right")
    ax.set_title(f"A1 Harare-Chirundu, km {km_from:g}-{km_to:g} ({z[0]:.0f} m to {z[-1]:.0f} m)", fontsize=13)
    a_g = np.abs(g)
    colors = np.where(a_g < 4, "#2e9e44", np.where(a_g < 6, "#e6c229", np.where(a_g < 8, "#f07c1f", "#d62728")))
    axg.bar(ch, g, width=step, color=colors)
    axg.axhline(0, color="black", lw=0.5)
    axg.set_ylabel("Gradient %\n(200 m base)")
    axg.set_xlabel("Chainage from Harare (km)")
    axg.grid(alpha=0.3)
    axg.set_xlim(km_from, km_to)
    plt.tight_layout()
    plt.savefig(out)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4])
