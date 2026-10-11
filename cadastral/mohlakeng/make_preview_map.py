import sys
import geopandas as gpd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
g = sys.argv[1]
e = gpd.read_file(g, layer="Mohlakeng_erven"); p = gpd.read_file(g, layer="Mohlakeng_public_places"); f = gpd.read_file(g, layer="Mohlakeng_farm_portions")
fig, ax = plt.subplots(figsize=(11, 12), dpi=150)
f.boundary.plot(ax=ax, color="#c0392b", linewidth=0.9)
reg = e[e.LSTATUS == "R"]; srv = e[e.LSTATUS != "R"]
srv.plot(ax=ax, facecolor="#f3e3b5", edgecolor="#8a6d1f", linewidth=0.12)
reg.plot(ax=ax, facecolor="#cfe0f3", edgecolor="#2c5a8a", linewidth=0.12)
p.plot(ax=ax, facecolor="#7fc97f", edgecolor="#2e7d32", linewidth=0.4)
xmin, ymin, xmax, ymax = e.total_bounds; ax.set_xlim(xmin - .004, xmax + .004); ax.set_ylim(ymin - .003, ymax + .003)
ax.set_title(f"Mohlakeng cadastre — {len(e):,} erven (Surveyor-General data)", fontsize=13)
ax.legend(handles=[Patch(facecolor="#cfe0f3", edgecolor="#2c5a8a", label=f"Erven, status R ({len(reg):,})"),
                   Patch(facecolor="#f3e3b5", edgecolor="#8a6d1f", label=f"Erven, status S ({len(srv):,})"),
                   Patch(facecolor="#7fc97f", edgecolor="#2e7d32", label=f"Public places ({len(p)})"),
                   Line2D([], [], color="#c0392b", label="Farm portion boundaries")], loc="lower left", fontsize=9, framealpha=.9)
ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude"); ax.tick_params(labelsize=8)
plt.tight_layout(); plt.savefig(sys.argv[2])
