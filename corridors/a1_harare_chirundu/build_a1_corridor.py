"""Inception-level terrain package for the A1 Harare-Chirundu road, Zimbabwe (now route R3).

Builds, from free global data:
  * the road centreline from Harare to the Zimbabwe bank of the Zambezi bridge at Chirundu
    (Overture Maps transportation data, which is derived from OpenStreetMap);
  * a longitudinal profile sampled every 10 m from the Copernicus GLO-30 DEM, cross-checked
    against SRTM, with bridges, river crossings and other spurious drops detected and corrected;
  * gradients over a 200 m base, classified and grouped into steep sections;
  * 10 m contours (50 m index) in a corridor 1 km either side of the centreline.

Outputs: KMZ (Google Earth), DXF plan (UTM 35S) and DXF long section (AutoCAD), LandXML alignment
with existing-ground profiles and a GeoTIFF corridor surface (Civil 3D), Excel tables, a profile
chart and a steep-section map.

Usage:
    pip install geopandas pyarrow rasterio contourpy ezdxf networkx scipy pyproj matplotlib openpyxl
    python build_a1_corridor.py OUTPUT_DIR CACHE_DIR
"""

import gzip
import json
import math
import shutil
import os
import sys
import urllib.request
import zipfile
from xml.sax.saxutils import escape

import contourpy
import ezdxf
import matplotlib
import networkx as nx
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import rasterio
import rasterio.features
import rasterio.merge
import rasterio.warp
import rasterio.windows
import shapely
import shapely.wkb
from pyproj import Geod, Transformer
from scipy import ndimage
from shapely.ops import substring

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

OVERTURE = "overturemaps-us-west-2/release/2026-09-23.1/"
BBOX = (28.75, -17.95, 31.15, -15.95)  # lon/lat search box around the corridor
DEM_TILES = [(lat, lon) for lat in (17, 18) for lon in (28, 29, 30, 31)]  # S17-S18, E028-E031

STEP = 10                 # profile sample spacing (m)
STATION = 20              # station spacing in the Excel profile (m)
GRADE_BASE = 200          # gradients are measured over this distance (m)
HALF_WIDTH = 1000         # contour corridor half-width (m)
CONTOUR, INDEX = 10, 50   # contour and index-contour interval (m)
SPIKE_LIMIT = 5.0         # deviation from the 310 m running median treated as an anomaly (m)
MAX_FIX = 300             # anomalies longer than this are flagged but not corrected (m)
POSITION_ERROR = 30       # assumed centreline position error for the sensitivity check (m)
SENSITIVE = 5.0           # height change from that error that makes a section low-confidence (m)
GRADE_CLASSES = [(0, 4, "0-4%", "#2e9e44"), (4, 6, "4-6%", "#e6c229"),
                 (6, 8, "6-8%", "#f07c1f"), (8, 99, ">8%", "#d62728")]

GEOD = Geod(ellps="WGS84")
UTM = "EPSG:32735"  # WGS 84 / UTM zone 35S
TO_UTM = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
TO_LL = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)


def to_utm(geom):
    return shapely.transform(geom, TO_UTM.transform, interleaved=False)


def to_ll(geom):
    return shapely.transform(geom, TO_LL.transform, interleaved=False)


# ----------------------------------------------------------------------------- data download

def overture(cache, name, theme, columns, extra):
    path = os.path.join(cache, f"overture_{name}.parquet")
    if not os.path.exists(path):
        fs = pafs.S3FileSystem(anonymous=True, region="us-west-2",
                               proxy_options=os.environ.get("HTTPS_PROXY") or None,
                               tls_ca_file_path=os.environ.get("AWS_CA_BUNDLE", ""))
        d = ds.dataset(OVERTURE + theme, filesystem=fs, format="parquet")
        w, s, e, n = BBOX
        flt = ((ds.field("bbox", "xmax") >= w) & (ds.field("bbox", "xmin") <= e) &
               (ds.field("bbox", "ymax") >= s) & (ds.field("bbox", "ymin") <= n) & extra)
        pq.write_table(d.to_table(columns=columns, filter=flt), path)
    return pq.read_table(path).to_pylist()


def dem_tiles(cache):
    paths = {"cop": [], "srtm": []}
    for lat, lon in DEM_TILES:
        cop = f"Copernicus_DSM_COG_10_S{lat}_00_E{lon:03d}_00_DEM"
        srtm = f"S{lat}E{lon:03d}"
        for kind, url, fname in (
                ("cop", f"https://copernicus-dem-30m.s3.amazonaws.com/{cop}/{cop}.tif", f"{cop}.tif"),
                ("srtm", f"https://elevation-tiles-prod.s3.amazonaws.com/skadi/S{lat}/{srtm}.hgt.gz",
                 f"{srtm}.hgt.gz")):
            path = os.path.join(cache, fname.removesuffix(".gz"))
            if not os.path.exists(path):
                urllib.request.urlretrieve(url, path + ".download")
                if fname.endswith(".gz"):
                    with gzip.open(path + ".download") as src, open(path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    os.remove(path + ".download")
                else:
                    os.rename(path + ".download", path)
            paths[kind].append(path)
    return paths


def mosaic(paths):
    arr, transform = rasterio.merge.merge(paths, bounds=BBOX, nodata=np.nan, dtype="float32")
    arr = arr[0]
    arr[arr <= -1000] = np.nan  # SRTM voids
    return arr, transform


def bilinear(arr, transform, lon, lat):
    col = (np.asarray(lon) - transform.c) / transform.a - 0.5
    row = (np.asarray(lat) - transform.f) / transform.e - 0.5
    return ndimage.map_coordinates(arr, [row, col], order=1, mode="nearest", cval=np.nan)


# ----------------------------------------------------------------------------- centreline

def route_refs(seg):
    return {(r["ref"] or r["name"] or "") for r in (seg["routes"] or [])}


def build_centreline(cache):
    segs = overture(cache, "roads", "theme=transportation/type=segment/",
                    ["id", "names", "class", "connectors", "road_flags", "routes", "geometry", "bbox"],
                    ds.field("class").isin(["motorway", "trunk", "primary", "secondary"]))
    graph = nx.Graph()
    for seg in segs:
        refs = route_refs(seg)
        # R3 is the current number of the old A1; SADC 22 runs on it and continues into Zambia.
        if "R3" not in refs and not refs & {"SADC 22 (westbound)", "SADC 22 (eastbound)"}:
            continue
        line = shapely.wkb.loads(seg["geometry"])
        cons = sorted(seg["connectors"] or [], key=lambda c: c["at"])
        bridges = [tuple(f["between"] or (0.0, 1.0)) for f in (seg["road_flags"] or [])
                   if "is_bridge" in f["values"]]
        for a, b in zip(cons, cons[1:]):
            part = substring(line, a["at"], b["at"], normalized=True)
            if part.length == 0:
                continue
            length = GEOD.geometry_length(part)
            graph.add_edge(a["connector_id"], b["connector_id"], geom=part, length=length,
                           weight=length * (1.0 if "R3" in refs else 1.5),
                           bridges=[((max(lo, a["at"]) - a["at"]) / (b["at"] - a["at"]),
                                     (min(hi, b["at"]) - a["at"]) / (b["at"] - a["at"]))
                                    for lo, hi in bridges if hi > a["at"] and lo < b["at"]])
            graph.nodes[a["connector_id"]]["xy"] = part.coords[0]
            graph.nodes[b["connector_id"]]["xy"] = part.coords[-1]

    start = max(graph.nodes, key=lambda n: graph.nodes[n]["xy"][0])  # eastern end, central Harare
    end = min(graph.nodes, key=lambda n: graph.nodes[n]["xy"][0])    # western end, in Zambia
    path = nx.shortest_path(graph, start, end, weight="weight")

    coords, bridges, chain = [], [], 0.0
    for u, v in zip(path, path[1:]):
        edge = graph.edges[u, v]
        pts = list(edge["geom"].coords)
        forward = pts[0] == graph.nodes[u]["xy"]
        if not forward:
            pts = pts[::-1]
        for f0, f1 in edge["bridges"]:
            if not forward:
                f0, f1 = 1 - f1, 1 - f0
            bridges.append([chain + f0 * edge["length"], chain + f1 * edge["length"]])
        coords += pts if not coords else pts[1:]
        chain += edge["length"]

    # Merge bridge pieces split at connectors, then stop at the Zambezi bridge: the longest
    # bridge in the last 30 km before the western end of the route.
    bridges.sort()
    merged = []
    for b in bridges:
        if merged and b[0] - merged[-1][1] < 1:
            merged[-1][1] = max(merged[-1][1], b[1])
        else:
            merged.append(b)
    zambezi = max((b for b in merged if b[0] > chain - 30000), key=lambda b: b[1] - b[0])
    lon, lat = np.array(coords).T
    vertex_ch = np.concatenate([[0], np.cumsum(GEOD.line_lengths(lon, lat))])
    end_ch = zambezi[0]
    ch = np.arange(0, end_ch, STEP)
    ch = np.append(ch, end_ch) if end_ch - ch[-1] > 1 else ch
    return {"ch": ch, "lon": np.interp(ch, vertex_ch, lon), "lat": np.interp(ch, vertex_ch, lat),
            "bridges": [b for b in merged if b[1] <= end_ch], "zambezi": zambezi}


def water_crossings(cache, cl):
    water = overture(cache, "water", "theme=base/type=water/",
                     ["id", "names", "subtype", "class", "geometry", "bbox"],
                     ds.field("subtype").isin(["river", "stream", "canal"]))
    line = shapely.LineString(zip(cl["lon"], cl["lat"]))
    utm_line = to_utm(line)
    tree = shapely.STRtree([shapely.wkb.loads(w["geometry"]) for w in water])
    out = []
    for idx in tree.query(line, predicate="intersects"):
        w = water[idx]
        geom = shapely.wkb.loads(w["geometry"])
        if geom.geom_type not in ("LineString", "MultiLineString"):
            continue
        hits = line.intersection(geom)
        for p in getattr(hits, "geoms", [hits]):
            if p.geom_type != "Point":
                continue
            # Chainage of the crossing: project in UTM, scale to the geodesic chainage.
            frac = utm_line.project(shapely.Point(TO_UTM.transform(p.x, p.y))) / utm_line.length
            out.append({"ch": frac * cl["ch"][-1], "name": (w["names"] or {}).get("primary") or "",
                        "class": w["class"] or w["subtype"]})
    return sorted(out, key=lambda c: c["ch"])


def towns_along(cache, cl):
    places = overture(cache, "places", "theme=divisions/type=division/",
                      ["id", "names", "subtype", "class", "population", "geometry", "country"],
                      ds.field("subtype") == "locality")
    utm_line = to_utm(shapely.LineString(zip(cl["lon"], cl["lat"])))
    out = []
    for p in places:
        if p["country"] != "ZW" or p["class"] not in ("city", "town"):
            continue
        pt = shapely.wkb.loads(p["geometry"])
        upt = shapely.Point(TO_UTM.transform(pt.x, pt.y))
        if utm_line.distance(upt) < 3000:
            out.append({"name": p["names"]["primary"],
                        "ch": utm_line.project(upt) / utm_line.length * cl["ch"][-1]})
    out.append({"name": "Chirundu (Zambezi bridge)", "ch": cl["ch"][-1]})
    return sorted(out, key=lambda t: t["ch"])


# ----------------------------------------------------------------------------- profile

def running_median(z, window):
    s = pd.Series(z)
    return s.rolling(window, center=True, min_periods=window // 3).median().to_numpy()


def clean_profile(cl, z_cop, z_srtm, crossings):
    ch = cl["ch"]
    z = z_cop.copy()
    events = []

    def interp_over(i0, i1):
        z[i0:i1 + 1] = np.interp(ch[i0:i1 + 1], [ch[i0], ch[i1]], [z[i0], z[i1]])

    # 1. Tagged bridges: the DEM sees the valley floor, so carry the line across the abutments.
    for b0, b1 in cl["bridges"]:
        i0 = max(int(np.searchsorted(ch, b0 - 20)) - 1, 0)
        i1 = min(int(np.searchsorted(ch, b1 + 20)), len(ch) - 1)
        before = z[i0:i1 + 1].copy()
        interp_over(i0, i1)
        events.append({"ch_from": ch[i0], "ch_to": ch[i1], "type": "Bridge (in map data)",
                       "max_drop_m": float(np.nanmax(z[i0:i1 + 1] - before)),
                       "corrected": "Yes - line carried across the bridge",
                       "detail": f"Bridge length {b1 - b0:.0f} m"})

    # 2. Remaining spikes and drops against a 310 m running median.
    dev = z - running_median(z, 31)
    bad = np.abs(dev) > SPIKE_LIMIT
    labels, n = ndimage.label(ndimage.binary_closing(bad, structure=np.ones(4)))
    cross_ch = np.array([c["ch"] for c in crossings])
    for k in range(1, n + 1):
        idx = np.flatnonzero(labels == k)
        i0, i1 = max(idx[0] - 3, 0), min(idx[-1] + 3, len(ch) - 1)
        seg_dev = dev[idx]
        worst = seg_dev[np.nanargmax(np.abs(seg_dev))]
        disagree = np.nanmax(np.abs(z_cop[i0:i1 + 1] - z_srtm[i0:i1 + 1]))
        near = [c for c in crossings if ch[i0] - 50 <= c["ch"] <= ch[i1] + 50] if len(cross_ch) else []
        if near and worst < 0:
            kind = "Watercourse crossing - bridge or culvert not in map data"
            detail = ", ".join(sorted({(c["name"] or c["class"]) for c in near}))
        elif disagree > 10:
            kind = "Elevation models disagree (trees, buildings or data error)"
            detail = f"Copernicus vs SRTM differ by up to {disagree:.0f} m"
        elif worst > 0:
            kind = "Spike - probably trees, buildings or a cutting edge"
            detail = ""
        else:
            kind = "Drop - no obvious cause, check on site or on imagery"
            detail = ""
        fixable = ch[i1] - ch[i0] <= MAX_FIX
        if fixable:
            interp_over(i0, i1)
        events.append({"ch_from": ch[i0], "ch_to": ch[i1], "type": kind,
                       "max_drop_m": float(-worst), "corrected":
                       "Yes - interpolated" if fixable else "No - too long, check", "detail": detail})
    return z, sorted(events, key=lambda e: e["ch_from"])


def gradients(ch, z):
    h = GRADE_BASE // STEP // 2
    zp = np.pad(z, h, mode="edge")
    run = np.full(len(z), float(GRADE_BASE))
    run[:h] = np.arange(h, 2 * h) * STEP
    run[-h:] = np.arange(2 * h - 1, h - 1, -1) * STEP
    return (zp[2 * h:] - zp[:-2 * h]) / run * 100


def grade_class(g):
    a = np.abs(g)
    return np.select([a < 4, a < 6, a < 8], [0, 1, 2], 3)


def steep_sections(ch, z, g, min_grade=6, min_len=100, join=250):
    steep = np.abs(g) >= min_grade
    labels, n = ndimage.label(steep)
    runs = []
    for k in range(1, n + 1):
        idx = np.flatnonzero(labels == k)
        if runs and ch[idx[0]] - runs[-1][1] <= join:
            runs[-1][1] = ch[idx[-1]]
        else:
            runs.append([ch[idx[0]], ch[idx[-1]]])
    out = []
    for c0, c1 in runs:
        if c1 - c0 < min_len:
            continue
        sel = (ch >= c0) & (ch <= c1)
        z0, z1 = np.interp([c0, c1], ch, z)
        out.append({"ch_from": c0, "ch_to": c1, "length_m": c1 - c0,
                    "elev_from": z0, "elev_to": z1, "avg_grade": float(np.mean(g[sel])),
                    "max_grade": float(np.max(np.abs(g[sel]))),
                    "direction": "Downhill" if z1 < z0 else "Uphill"})
    return out


def position_sensitivity(arr, transform, cl, z_cop, offset):
    """Largest height change at each point if the centreline were `offset` m to either side."""
    e, n = TO_UTM.transform(cl["lon"], cl["lat"])
    de, dn = np.gradient(e), np.gradient(n)
    length = np.hypot(de, dn)
    ne, nn = -dn / length, de / length
    worst = np.zeros(len(e))
    for sign in (-1, 1):
        lon, lat = TO_LL.transform(e + sign * offset * ne, n + sign * offset * nn)
        worst = np.maximum(worst, np.abs(bilinear(arr, transform, lon, lat) - z_cop))
    return worst


def runs_of(ch, mask, min_len=50):
    labels, n = ndimage.label(mask)
    out = []
    for k in range(1, n + 1):
        idx = np.flatnonzero(labels == k)
        if ch[idx[-1]] - ch[idx[0]] >= min_len:
            out.append((ch[idx[0]], ch[idx[-1]]))
    return out


# ----------------------------------------------------------------------------- contours

def corridor_polygon(cl):
    utm_line = shapely.LineString(zip(*TO_UTM.transform(cl["lon"], cl["lat"])))
    return utm_line.buffer(HALF_WIDTH)


def make_contours(arr, transform, corridor_utm):
    poly_ll = to_ll(corridor_utm)
    win = rasterio.windows.from_bounds(*poly_ll.bounds, transform=transform).round_offsets().round_lengths()
    r0, c0 = int(win.row_off), int(win.col_off)
    sub = arr[r0:r0 + int(win.height), c0:c0 + int(win.width)]
    sub_t = rasterio.windows.transform(win, transform)
    mask = rasterio.features.geometry_mask([poly_ll], sub.shape, sub_t, invert=True)
    filled = np.where(np.isnan(sub), np.nanmean(sub), sub)
    smooth = ndimage.gaussian_filter(filled, 1.0)  # ~30 m: suppresses canopy noise, keeps landform
    z = np.ma.masked_array(smooth, ~mask)
    x = sub_t.c + (np.arange(sub.shape[1]) + 0.5) * sub_t.a
    y = sub_t.f + (np.arange(sub.shape[0]) + 0.5) * sub_t.e
    gen = contourpy.contour_generator(x, y, z, line_type=contourpy.LineType.Separate)
    lo = math.ceil(np.nanmin(z.compressed()) / CONTOUR) * CONTOUR
    hi = math.floor(np.nanmax(z.compressed()) / CONTOUR) * CONTOUR
    out = []
    for level in range(lo, hi + 1, CONTOUR):
        for line in gen.lines(level):
            if len(line) < 3:
                continue
            utm = shapely.LineString(zip(*TO_UTM.transform(line[:, 0], line[:, 1]))).simplify(2.0)
            if utm.length < 30:
                continue
            out.append({"z": level, "index": level % INDEX == 0, "utm": np.array(utm.coords)})
    return out


# ----------------------------------------------------------------------------- outputs

def kml_color(hex_rgb, alpha="ff"):
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"{alpha}{b}{g}{r}"


def write_kmz(path, cl, z, g, cls, contours, events, steep, towns, low_conf):
    def coords(lon, lat):
        return " ".join(f"{x:.6f},{y:.6f}" for x, y in zip(lon, lat))

    def placemark(name, style, geom, desc=""):
        return (f"<Placemark><name>{escape(name)}</name><styleUrl>#{style}</styleUrl>"
                f"<description><![CDATA[{desc}]]></description>{geom}</Placemark>")

    styles = "".join(
        f'<Style id="g{i}"><LineStyle><color>{kml_color(c[3])}</color><width>5</width></LineStyle></Style>'
        for i, c in enumerate(GRADE_CLASSES))
    styles += ('<Style id="cminor"><LineStyle><color>ff2a5a8b</color><width>0.8</width></LineStyle></Style>'
               '<Style id="cindex"><LineStyle><color>ff13457a</color><width>1.8</width></LineStyle></Style>'
               '<Style id="lowconf"><LineStyle><color>99b4409c</color><width>12</width></LineStyle></Style>'
               '<Style id="km"><IconStyle><scale>0.6</scale><Icon><href>'
               'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>'
               '<LabelStyle><scale>0.8</scale></LabelStyle></Style>'
               '<Style id="flag"><IconStyle><color>ff0000ff</color><Icon><href>'
               'http://maps.google.com/mapfiles/kml/shapes/caution.png</href></Icon></IconStyle>'
               '<LabelStyle><scale>0</scale></LabelStyle></Style>'
               '<Style id="bridge"><IconStyle><color>ffffaa00</color><Icon><href>'
               'http://maps.google.com/mapfiles/kml/shapes/square.png</href></Icon></IconStyle>'
               '<LabelStyle><scale>0</scale></LabelStyle></Style>')

    # Centreline split into runs of one gradient class.
    road = []
    breaks = np.flatnonzero(np.diff(cls)) + 1
    for s0, s1 in zip(np.r_[0, breaks], np.r_[breaks, len(cls)]):
        s1 = min(s1 + 1, len(cls))
        c = GRADE_CLASSES[cls[s0]]
        road.append(placemark(
            f"{c[2]} km {cl['ch'][s0] / 1000:.2f}-{cl['ch'][s1 - 1] / 1000:.2f}", f"g{cls[s0]}",
            f"<LineString><tessellate>1</tessellate><coordinates>{coords(cl['lon'][s0:s1], cl['lat'][s0:s1])}"
            f"</coordinates></LineString>"))

    kms = []
    for km in range(0, int(cl["ch"][-1] // 1000) + 1):
        i = int(np.searchsorted(cl["ch"], km * 1000))
        kms.append(placemark(f"km {km}" if km % 5 == 0 else "", "km",
                             f"<Point><coordinates>{cl['lon'][i]:.6f},{cl['lat'][i]:.6f}</coordinates></Point>",
                             f"Chainage {km} km<br>Elevation {z[i]:.0f} m<br>Gradient {g[i]:+.1f}%"))

    flags, bridges = [], []
    for e in events:
        i = int(np.searchsorted(cl["ch"], (e["ch_from"] + e["ch_to"]) / 2))
        desc = (f"km {e['ch_from'] / 1000:.3f} - {e['ch_to'] / 1000:.3f}<br>{escape(e['type'])}<br>"
                f"Raw DEM drop: {e['max_drop_m']:+.1f} m<br>Corrected: {e['corrected']}<br>{escape(e['detail'])}")
        pt = f"<Point><coordinates>{cl['lon'][i]:.6f},{cl['lat'][i]:.6f}</coordinates></Point>"
        (bridges if e["type"].startswith("Bridge") else flags).append(
            placemark(f"km {e['ch_from'] / 1000:.2f}: {e['type']}", "bridge" if e["type"].startswith("Bridge")
                      else "flag", pt, desc))

    lowc = []
    for c0, c1 in low_conf:
        sel = (cl["ch"] >= c0) & (cl["ch"] <= c1)
        lowc.append(placemark(f"km {c0 / 1000:.2f}-{c1 / 1000:.2f}", "lowconf",
                              f"<LineString><tessellate>1</tessellate><coordinates>"
                              f"{coords(cl['lon'][sel], cl['lat'][sel])}</coordinates></LineString>",
                              f"If the centreline is {POSITION_ERROR} m out here, the height changes by more than "
                              f"{SENSITIVE:.0f} m. Check the road position on imagery before trusting the profile."))

    cont = {True: [], False: []}
    for c in contours:
        lon, lat = TO_LL.transform(c["utm"][:, 0], c["utm"][:, 1])
        cont[c["index"]].append(placemark(f"{c['z']} m", "cindex" if c["index"] else "cminor",
                                          f"<LineString><tessellate>1</tessellate><coordinates>{coords(lon, lat)}"
                                          f"</coordinates></LineString>"))

    steep_rows = "".join(
        f"<tr><td>{s['ch_from'] / 1000:.2f}-{s['ch_to'] / 1000:.2f}</td><td>{s['length_m']:.0f} m</td>"
        f"<td>{s['avg_grade']:+.1f}%</td><td>{s['max_grade']:.1f}%</td></tr>" for s in steep)

    def folder(name, items, visible=1):
        return f"<Folder><name>{escape(name)}</name><visibility>{visible}</visibility>{''.join(items)}</Folder>"

    doc = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           "<name>A1 Harare-Chirundu terrain (inception level)</name>"
           f"<description><![CDATA[Copernicus GLO-30 DEM, 10 m contours, gradients over {GRADE_BASE} m. "
           f"Steep sections (6% or more):<table border='1'><tr><th>km</th><th>Length</th><th>Avg</th>"
           f"<th>Max</th></tr>{steep_rows}</table>]]></description>{styles}"
           + folder("Centreline coloured by gradient", road)
           + folder("Kilometre markers", kms)
           + folder("Profile problems found and corrected", flags)
           + folder("Bridges", bridges)
           + folder(f"Position-sensitive sections (height changes >{SENSITIVE:.0f} m if centreline {POSITION_ERROR} m out)", lowc)
           + folder("Contours 50 m (index)", cont[True])
           + folder("Contours 10 m", cont[False])
           + folder("Towns", [placemark(t["name"], "km", "<Point><coordinates>"
                                         f"{np.interp(t['ch'], cl['ch'], cl['lon']):.6f},"
                                         f"{np.interp(t['ch'], cl['ch'], cl['lat']):.6f}</coordinates></Point>")
                              for t in towns])
           + "</Document></kml>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", doc)


def write_plan_dxf(path, cl, z, cls, contours, events, steep):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    layers = {"CONTOUR_10M": 33, "CONTOUR_INDEX_50M": 34, "CENTRELINE": 7, "CHAINAGE": 7,
              "GRADE_0-4": 3, "GRADE_4-6": 2, "GRADE_6-8": 30, "GRADE_GT8": 1, "PROFILE_FLAGS": 6}
    for name, color in layers.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    for c in contours:
        msp.add_lwpolyline(c["utm"], dxfattribs={
            "layer": "CONTOUR_INDEX_50M" if c["index"] else "CONTOUR_10M", "elevation": float(c["z"])})
    e, n = TO_UTM.transform(cl["lon"], cl["lat"])
    msp.add_polyline3d(list(zip(e, n, z)), dxfattribs={"layer": "CENTRELINE"})
    grade_layers = ["GRADE_0-4", "GRADE_4-6", "GRADE_6-8", "GRADE_GT8"]
    breaks = np.flatnonzero(np.diff(cls)) + 1
    for s0, s1 in zip(np.r_[0, breaks], np.r_[breaks, len(cls)]):
        s1 = min(s1 + 1, len(cls))
        msp.add_lwpolyline(list(zip(e[s0:s1], n[s0:s1])),
                           dxfattribs={"layer": grade_layers[cls[s0]], "const_width": 15})
    for km in range(0, int(cl["ch"][-1] // 1000) + 1):
        i = min(int(np.searchsorted(cl["ch"], km * 1000)), len(e) - 2)
        dx, dy = e[i + 1] - e[i], n[i + 1] - n[i]
        nx_, ny_ = -dy / math.hypot(dx, dy), dx / math.hypot(dx, dy)
        tick = 60 if km % 5 == 0 else 30
        msp.add_line((e[i] - nx_ * tick, n[i] - ny_ * tick), (e[i] + nx_ * tick, n[i] + ny_ * tick),
                     dxfattribs={"layer": "CHAINAGE"})
        if km % 5 == 0:
            msp.add_text(f"km {km}", height=40, dxfattribs={"layer": "CHAINAGE"}).set_placement(
                (e[i] + nx_ * 80, n[i] + ny_ * 80))
    for ev in events:
        i = int(np.searchsorted(cl["ch"], (ev["ch_from"] + ev["ch_to"]) / 2))
        i = min(i, len(e) - 1)
        msp.add_circle((e[i], n[i]), 25, dxfattribs={"layer": "PROFILE_FLAGS"})
        msp.add_text(f"{ev['type'].split(' -')[0].split(' (')[0]} {ev['max_drop_m']:+.0f}m", height=15,
                     dxfattribs={"layer": "PROFILE_FLAGS"}).set_placement((e[i] + 30, n[i] + 30))
    doc.saveas(path)


def write_long_section_dxf(path, cl, z_raw, z, g, events, steep, towns, vex=10):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for name, color in {"GROUND_RAW_DEM": 1, "GROUND_CORRECTED": 7, "GRID": 8, "TEXT": 7,
                        "BRIDGES": 5, "STEEP_6-8": 30, "STEEP_GT8": 1, "FLAGS": 6}.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    ch = cl["ch"]
    base = math.floor((np.nanmin(z) - 50) / 100) * 100
    top = math.ceil((np.nanmax(z) + 50) / 100) * 100

    def y(elev):
        return (np.asarray(elev) - base) * vex

    step = 5  # every 50 m is plenty for a drawing
    msp.add_lwpolyline(list(zip(ch[::step], y(z_raw[::step]))), dxfattribs={"layer": "GROUND_RAW_DEM"})
    msp.add_lwpolyline(list(zip(ch[::step], y(z[::step]))), dxfattribs={"layer": "GROUND_CORRECTED"})
    for elev in range(base, top + 1, 100):
        msp.add_line((0, y(elev)), (ch[-1], y(elev)), dxfattribs={"layer": "GRID"})
        msp.add_text(f"{elev} m", height=120, dxfattribs={"layer": "TEXT"}).set_placement((-1500, y(elev)))
    for km in range(0, int(ch[-1] // 1000) + 1):
        x = km * 1000
        if km % 5 == 0:
            msp.add_line((x, 0), (x, y(top)), dxfattribs={"layer": "GRID"})
            msp.add_text(f"km {km}", height=150, dxfattribs={"layer": "TEXT"}).set_placement((x - 400, -400))
    for t in towns:
        msp.add_text(t["name"], height=200, dxfattribs={"layer": "TEXT"}).set_placement(
            (t["ch"], y(top) + 300))
    for ev in events:
        layer = "BRIDGES" if ev["type"].startswith("Bridge") else "FLAGS"
        x = (ev["ch_from"] + ev["ch_to"]) / 2
        msp.add_line((x, y(np.interp(x, ch, z)) + 200), (x, y(np.interp(x, ch, z)) + 900),
                     dxfattribs={"layer": layer})
    for s in steep:
        layer = "STEEP_GT8" if s["max_grade"] >= 8 else "STEEP_6-8"
        msp.add_lwpolyline([(s["ch_from"], -900), (s["ch_to"], -900)],
                           dxfattribs={"layer": layer, "const_width": 150})
    msp.add_text(f"A1 Harare-Chirundu long section. Horizontal 1:1 (m), vertical exaggeration x{vex}. "
                 f"Red: raw Copernicus DEM. White: corrected. Bars: steep sections (orange 6-8%, red >8%).",
                 height=250, dxfattribs={"layer": "TEXT"}).set_placement((0, y(top) + 900))
    doc.saveas(path)


def civil3d_alignment(cl):
    """Alignment in UTM 35S (straight segments within 1 m of the mapped centreline) and the
    station of every profile point on it. Civil 3D stations are grid distances, so they run
    slightly ahead of the ground (geodesic) chainage used elsewhere in this package."""
    e, n = TO_UTM.transform(cl["lon"], cl["lat"])
    align = shapely.LineString(zip(e, n)).simplify(1.0)
    return align, np.array([align.project(shapely.Point(p)) for p in zip(e, n)])


def write_landxml(path, align, sta, z, z_cop):
    """Civil 3D: alignment with corrected and raw existing-ground profiles."""
    pts = np.array(align.coords)
    every = STATION // STEP
    idx = np.unique(np.r_[np.arange(0, len(sta), every), len(sta) - 1])

    def plist(values):
        return " ".join(f"{sta[i]:.2f} {values[i]:.2f}" for i in idx)

    lines, st = [], 0.0
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        lines.append(f'<Line staStart="{st:.3f}" length="{length:.3f}"><Start>{y0:.3f} {x0:.3f}</Start>'
                     f"<End>{y1:.3f} {x1:.3f}</End></Line>")
        st += length
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" '
           f'date="{pd.Timestamp.now():%Y-%m-%d}" time="{pd.Timestamp.now():%H:%M:%S}">\n'
           '<Units><Metric areaUnit="squareMeter" linearUnit="meter" volumeUnit="cubicMeter" '
           'temperatureUnit="celsius" pressureUnit="milliBars" angularUnit="decimal degrees" '
           'directionUnit="decimal degrees"/></Units>\n'
           '<CoordinateSystem name="WGS 84 / UTM zone 35S" epsgCode="32735" horizontalDatum="WGS84" '
           'verticalDatum="EGM2008"/>\n'
           '<Application name="build_a1_corridor.py" desc="A1 Harare-Chirundu inception terrain package"/>\n'
           '<Alignments name="A1 Harare-Chirundu">\n'
           f'<Alignment name="A1 Harare-Chirundu centreline" length="{st:.3f}" staStart="0" '
           'desc="Mapped centreline (OpenStreetMap via Overture), straight segments within 1 m">\n'
           f"<CoordGeom>{''.join(lines)}</CoordGeom>\n"
           '<Profile name="Existing ground">\n'
           f'<ProfSurf name="EG corrected (Copernicus, bridges and spikes removed)"><PntList2D>{plist(z)}'
           "</PntList2D></ProfSurf>\n"
           f'<ProfSurf name="EG raw Copernicus DEM"><PntList2D>{plist(z_cop)}</PntList2D></ProfSurf>\n'
           "</Profile>\n</Alignment>\n</Alignments>\n</LandXML>\n")
    with open(path, "w") as f:
        f.write(xml)
    return st, len(lines)


def write_surface_tif(path, arr, transform, corridor_utm, res=30):
    """Civil 3D surface source: the Copernicus DEM in UTM 35S, clipped to the contour corridor."""
    minx, miny, maxx, maxy = corridor_utm.bounds
    width, height = int(math.ceil((maxx - minx) / res)), int(math.ceil((maxy - miny) / res))
    dst_t = rasterio.transform.from_origin(math.floor(minx / res) * res, math.ceil(maxy / res) * res, res, res)
    out = np.full((height, width), np.nan, dtype="float32")
    rasterio.warp.reproject(arr, out, src_transform=transform, src_crs="EPSG:4326", dst_transform=dst_t,
                            dst_crs=UTM, resampling=rasterio.warp.Resampling.bilinear,
                            src_nodata=np.nan, dst_nodata=np.nan)
    inside = rasterio.features.geometry_mask([corridor_utm], out.shape, dst_t, invert=True)
    out[~inside] = -9999
    out[np.isnan(out)] = -9999
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs=UTM, transform=dst_t, nodata=-9999, compress="deflate", predictor=3,
                       tiled=True) as dst:
        dst.write(out, 1)


def write_excel(path, cl, sta, z_cop, z_srtm, z, g, sens, events, steep, towns, crossings, low_conf, meta):
    e, n = TO_UTM.transform(cl["lon"], cl["lat"])
    every = STATION // STEP
    idx = np.r_[np.arange(0, len(cl["ch"]), every), len(cl["ch"]) - 1]
    idx = np.unique(idx)
    flags = np.full(len(cl["ch"]), "", dtype=object)
    for ev in events:
        sel = (cl["ch"] >= ev["ch_from"]) & (cl["ch"] <= ev["ch_to"])
        flags[sel] = ev["type"]
    profile = pd.DataFrame({
        "Chainage (m)": cl["ch"][idx].round(1), "Civil 3D station (m)": sta[idx].round(1),
        "Latitude": cl["lat"][idx].round(7),
        "Longitude": cl["lon"][idx].round(7), "Easting UTM35S (m)": np.round(e[idx], 2),
        "Northing UTM35S (m)": np.round(n[idx], 2), "Elevation corrected (m)": z[idx].round(1),
        "Copernicus raw (m)": z_cop[idx].round(1), "SRTM raw (m)": z_srtm[idx].round(1),
        f"Gradient over {GRADE_BASE} m (%)": g[idx].round(2),
        "Gradient class": [GRADE_CLASSES[c][2] for c in grade_class(g[idx])],
        f"Height change if centreline {POSITION_ERROR} m out (m)": sens[idx].round(1), "Note": flags[idx]})
    ev = pd.DataFrame(events).rename(columns={
        "ch_from": "From (m)", "ch_to": "To (m)", "type": "What it is",
        "max_drop_m": "Raw DEM drop (m, + = dip)", "corrected": "Corrected?", "detail": "Detail"}).round(1)
    st = pd.DataFrame(steep).rename(columns={
        "ch_from": "From (m)", "ch_to": "To (m)", "length_m": "Length (m)", "elev_from": "Elevation from (m)",
        "elev_to": "Elevation to (m)", "avg_grade": "Average grade (%)", "max_grade": "Max grade (%)",
        "direction": "Direction (towards Chirundu)"}).round(1)
    km = pd.DataFrame([{"km": k, "Chainage (m)": k * 1000,
                        "Elevation (m)": round(float(np.interp(k * 1000, cl["ch"], z)), 1),
                        "Latitude": round(float(np.interp(k * 1000, cl["ch"], cl["lat"])), 7),
                        "Longitude": round(float(np.interp(k * 1000, cl["ch"], cl["lon"])), 7)}
                       for k in range(0, int(cl["ch"][-1] // 1000) + 1)])
    tw = pd.DataFrame([{"Town": t["name"], "Chainage (km)": round(t["ch"] / 1000, 1),
                        "Elevation (m)": round(float(np.interp(t["ch"], cl["ch"], z)))} for t in towns])
    lc = pd.DataFrame([{"From (m)": round(a), "To (m)": round(b), "Length (m)": round(b - a)}
                       for a, b in low_conf])
    about = pd.DataFrame(list(meta.items()), columns=["Item", "Value"])
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        about.to_excel(xl, sheet_name="About", index=False)
        st.to_excel(xl, sheet_name="Steep sections", index=False)
        ev.to_excel(xl, sheet_name="Profile problems", index=False)
        lc.to_excel(xl, sheet_name="Position-sensitive sections", index=False)
        tw.to_excel(xl, sheet_name="Towns", index=False)
        km.to_excel(xl, sheet_name="Km markers", index=False)
        profile.to_excel(xl, sheet_name=f"Profile every {STATION} m", index=False)
        for ws in xl.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:300])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 90)


def plot_profile(path, cl, z_raw, z_srtm, z, g, events, steep, towns, low_conf):
    ch = cl["ch"] / 1000
    # Zoom on the 40 km window with the most steep road.
    steep_mask = np.abs(g) >= 6
    win = int(50000 / STEP)
    csum = np.convolve(steep_mask, np.ones(win), "valid")
    zs = int(np.argmax(csum))
    # Slide the window so it ends just past the last steep section it contains.
    in_win = [s for s in steep if s["ch_from"] / 1000 < ch[min(zs + win, len(ch) - 1)] and s["ch_to"] / 1000 > ch[zs]]
    x1 = min(ch[-1], max(s["ch_to"] for s in in_win) / 1000 + 4) if in_win else ch[min(zs + win, len(ch) - 1)]
    zoom = (max(0.0, x1 - 50), x1)

    fig, axes = plt.subplots(3, 1, figsize=(16, 13), dpi=130,
                             gridspec_kw={"height_ratios": [3, 0.5, 3]})
    for ax, (x0, x1) in ((axes[0], (0, ch[-1])), (axes[2], zoom)):
        sel = (ch >= x0) & (ch <= x1)
        for c0, c1 in low_conf:
            if c1 / 1000 >= x0 and c0 / 1000 <= x1:
                ax.axvspan(c0 / 1000, c1 / 1000, color="#b4409c", alpha=0.12, lw=0)
        ax.plot(ch[sel], z_raw[sel], color="#d62728", lw=0.6, alpha=0.8, label="Raw Copernicus DEM")
        if ax is axes[2]:
            ax.plot(ch[sel], z_srtm[sel], color="#7f7f7f", lw=0.6, alpha=0.8, label="Raw SRTM")
        ax.plot(ch[sel], z[sel], color="black", lw=1.1, label="Corrected profile")
        for ev in events:
            m = (ev["ch_from"] + ev["ch_to"]) / 2000
            if x0 <= m <= x1:
                bridge = ev["type"].startswith("Bridge")
                ax.plot(m, np.interp(m * 1000, cl["ch"], z) + (25 if ax is axes[0] else 8),
                        marker="s" if bridge else "v", ms=4, color="#1f77b4" if bridge else "#9467bd", ls="")
        top = np.nanmax(z[sel])
        for t in towns:
            if x0 <= t["ch"] / 1000 <= x1:
                ha = "left" if t["ch"] / 1000 - x0 < 0.03 * (x1 - x0) else (
                    "right" if x1 - t["ch"] / 1000 < 0.03 * (x1 - x0) else "center")
                ax.annotate(t["name"], (t["ch"] / 1000, np.interp(t["ch"], cl["ch"], z)),
                            xytext=(0, 28), textcoords="offset points", ha=ha, fontsize=8,
                            arrowprops={"arrowstyle": "-", "color": "#999", "lw": 0.6})
        ax.set_xlim(x0, x1)
        ax.set_ylim(np.nanmin(z[sel]) - 30, top + 0.12 * (top - np.nanmin(z[sel])) + 40)
        ax.set_ylabel("Elevation (m)")
        ax.grid(alpha=0.3)
    axes[0].set_title("A1 Harare-Chirundu longitudinal profile (Copernicus GLO-30, corrected)", fontsize=13)
    axes[0].axvspan(*zoom, color="#ffd27f", alpha=0.25, lw=0)
    handles = axes[2].get_legend_handles_labels()
    extra = [plt.Line2D([], [], marker="s", color="#1f77b4", ls="", label="Bridge (corrected)"),
             plt.Line2D([], [], marker="v", color="#9467bd", ls="", label="Other problem (see table)"),
             Patch(color="#b4409c", alpha=0.25, label=f"Height sensitive to centreline position")]
    axes[2].legend(handles=handles[0] + extra, loc="upper right", fontsize=8)
    axes[2].set_title(f"Zoom: km {zoom[0]:.0f}-{zoom[1]:.0f} (steepest 50 km)", fontsize=11)
    axes[2].set_xlabel("Chainage from Harare (km)")
    cls = grade_class(g)
    pts = np.column_stack([ch, np.zeros_like(ch)])
    segs = np.stack([pts[:-1], pts[1:]], axis=1)
    lc = LineCollection(segs, colors=[GRADE_CLASSES[c][3] for c in cls[:-1]], linewidths=18)
    axes[1].add_collection(lc)
    axes[1].set_xlim(0, ch[-1]); axes[1].set_ylim(-1, 1); axes[1].set_yticks([])
    axes[1].set_title(f"Gradient over {GRADE_BASE} m", fontsize=10, loc="left")
    axes[1].legend(handles=[Patch(color=c[3], label=c[2]) for c in GRADE_CLASSES],
                   loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=4, fontsize=8, frameon=False)
    plt.tight_layout()
    plt.savefig(path)
    plt.close(fig)
    return zoom


def plot_map(path, arr, transform, cl, g, towns, steep, zoom):
    step = 6
    a = arr[::step, ::step]
    t = transform * transform.scale(step, step)
    lat0 = np.deg2rad(np.mean(cl["lat"]))
    gy, gx = np.gradient(np.nan_to_num(a, nan=np.nanmean(a)), -t.e * 110570, t.a * 111320 * np.cos(lat0))
    shade = (np.cos(np.deg2rad(45)) * np.cos(np.arctan(np.hypot(gx, gy) * 2)) +
             np.sin(np.deg2rad(45)) * np.sin(np.arctan(np.hypot(gx, gy) * 2)) *
             np.cos(np.deg2rad(315) - np.arctan2(-gx, gy)))
    extent = (t.c, t.c + t.a * a.shape[1], t.f + t.e * a.shape[0], t.f)
    data_top = 1 - min(lat for lat, _ in DEM_TILES)  # northern edge of the DEM tiles (degrees, negative)
    cls = grade_class(g)
    land = matplotlib.colors.LinearSegmentedColormap.from_list(
        "land", ["#9fc58a", "#d9e0a3", "#e9d8a6", "#c9a77c", "#a58263", "#efe9e1"])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(17, 10), dpi=130, gridspec_kw={"width_ratios": [1.25, 1]})
    for axx in (ax, ax2):
        axx.imshow(a, extent=extent, cmap=land, vmin=350, vmax=1700, alpha=0.6)
        axx.imshow(shade, extent=extent, cmap="gray", alpha=0.35)
        pts = np.column_stack([cl["lon"], cl["lat"]])
        segs = np.stack([pts[:-1], pts[1:]], axis=1)
        axx.add_collection(LineCollection(segs, colors=[GRADE_CLASSES[c][3] for c in cls[:-1]],
                                          linewidths=3.5 if axx is ax else 5))
    for tw in towns:
        lon, lat = np.interp(tw["ch"], cl["ch"], cl["lon"]), np.interp(tw["ch"], cl["ch"], cl["lat"])
        ax.plot(lon, lat, "o", color="black", ms=4)
        right = lon > cl["lon"].max() - 0.3
        ax.annotate(f"{tw['name']} (km {tw['ch'] / 1000:.0f})", (lon, lat), xytext=(-6 if right else 6, 4),
                    textcoords="offset points", fontsize=9, ha="right" if right else "left")
    pad = 0.08
    lons = cl["lon"][(cl["ch"] >= zoom[0] * 1000) & (cl["ch"] <= zoom[1] * 1000)]
    lats = cl["lat"][(cl["ch"] >= zoom[0] * 1000) & (cl["ch"] <= zoom[1] * 1000)]
    zb = (lons.min() - pad, lons.max() + pad, lats.min() - pad, lats.max() + pad)
    ax.add_patch(plt.Rectangle((zb[0], zb[2]), zb[1] - zb[0], zb[3] - zb[2], fill=False, ec="black", lw=1, ls="--"))
    ax.set_xlim(cl["lon"].min() - 0.1, cl["lon"].max() + 0.1)
    ax.set_ylim(cl["lat"].min() - 0.1, min(cl["lat"].max() + 0.1, data_top))
    ax.set_title("A1 Harare-Chirundu: gradient along the road", fontsize=13)
    ax2.set_xlim(zb[0], zb[1]); ax2.set_ylim(zb[2], min(zb[3], data_top))
    ax2.set_title(f"Zoom: km {zoom[0]:.0f}-{zoom[1]:.0f}", fontsize=12)
    last = -1e9
    for s in steep:
        if zoom[0] * 1000 <= s["ch_from"] <= zoom[1] * 1000 and s["length_m"] >= 400 and s["ch_from"] - last > 2000:
            last = s["ch_from"]
            i = int(np.searchsorted(cl["ch"], (s["ch_from"] + s["ch_to"]) / 2))
            ax2.annotate(f"km {s['ch_from'] / 1000:.1f}: {s['avg_grade']:+.1f}% avg, max {s['max_grade']:.0f}%",
                         (cl["lon"][i], cl["lat"][i]), xytext=(8, 0), textcoords="offset points", fontsize=7.5,
                         bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.8, "lw": 0})
    for axx in (ax, ax2):
        axx.set_aspect(1 / np.cos(lat0))
        axx.tick_params(labelsize=8)
    ax.legend(handles=[Patch(color=c[3], label=f"Gradient {c[2]}") for c in GRADE_CLASSES],
              loc="upper right", fontsize=9)
    plt.tight_layout()
    plt.savefig(path)
    plt.close(fig)


# ----------------------------------------------------------------------------- main

def main(out_dir, cache):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(cache, exist_ok=True)
    print("Centreline...")
    cl = build_centreline(cache)
    crossings = water_crossings(cache, cl)
    towns = towns_along(cache, cl)
    print(f"  {cl['ch'][-1] / 1000:.2f} km, {len(cl['bridges'])} bridges, {len(crossings)} watercourse crossings")

    print("Elevation models...")
    tiles = dem_tiles(cache)
    cop, cop_t = mosaic(tiles["cop"])
    srtm, srtm_t = mosaic(tiles["srtm"])
    z_cop = bilinear(cop, cop_t, cl["lon"], cl["lat"])
    z_srtm = bilinear(srtm, srtm_t, cl["lon"], cl["lat"])
    del srtm

    print("Profile...")
    z, events = clean_profile(cl, z_cop, z_srtm, crossings)
    g = gradients(cl["ch"], z)
    cls = grade_class(g)
    steep = steep_sections(cl["ch"], z, g)
    sens = position_sensitivity(cop, cop_t, cl, z_cop, POSITION_ERROR)
    low_conf = runs_of(cl["ch"], ndimage.binary_closing(sens > SENSITIVE, np.ones(21)), min_len=100)
    worst_100 = position_sensitivity(cop, cop_t, cl, z_cop, 100)

    print("Contours...")
    contours = make_contours(cop, cop_t, corridor_polygon(cl))
    print(f"  {len(contours)} contour lines")

    diff = z_cop - z_srtm
    meta = {
        "Road": "A1 Harare-Chirundu (now numbered R3); km 0 in central Harare at "
                f"{cl['lat'][0]:.5f}, {cl['lon'][0]:.5f}",
        "End": f"Zimbabwe bank of the Zambezi bridge at Chirundu, km {cl['ch'][-1] / 1000:.2f} "
               f"({cl['lat'][-1]:.5f}, {cl['lon'][-1]:.5f})",
        "Centreline": "Overture Maps 2026-09-23 (from OpenStreetMap); accuracy typically 5-10 m",
        "Elevation": "Copernicus GLO-30 DSM (30 m, EGM2008 heights); SRTM 1 arc-second used as a cross-check",
        "Profile": f"Sampled every {STEP} m with bilinear interpolation; bridges and spikes/drops over "
                   f"{SPIKE_LIMIT:.0f} m from a 310 m running median corrected by interpolation",
        "Gradient": f"Measured over {GRADE_BASE} m (100 m either side of each point)",
        "Contours": f"{CONTOUR} m (index {INDEX} m), {HALF_WIDTH} m either side of the centreline; "
                    "DEM lightly smoothed (30 m Gaussian) before contouring",
        "Coordinates": "WGS 84 lat/long; DXF plan, LandXML and GeoTIFF in WGS 84 / UTM zone 35S (EPSG:32735). "
                       "Near Harare (outside zone 35) UTM distances read about 0.2% long",
        "Chainage vs Civil 3D station": "Chainage is measured on the ground (ellipsoid). Civil 3D stations are "
                                        "UTM grid distances and run about 0.07% ahead (242 m by Chirundu); "
                                        "both are listed in the profile sheet",
        "Copernicus minus SRTM along road": f"median {np.nanmedian(diff):+.1f} m, 90% within "
                                            f"{np.nanpercentile(np.abs(diff), 90):.1f} m",
        "Why profiles show sudden drops": (
            f"With this centreline the largest raw drop is {max((e['max_drop_m'] for e in events), default=0):.0f} m "
            f"(at a bridge). Moving the centreline {POSITION_ERROR} m sideways changes the height by up to "
            f"{sens.max():.0f} m; moving it 100 m changes it by up to {worst_100.max():.0f} m (km "
            f"{cl['ch'][np.argmax(worst_100)] / 1000:.1f}, Zambezi escarpment). Large drops therefore come from a "
            "centreline that is off the real road, mainly on the escarpment hairpins, and from bridges."),
        "Accuracy": "Inception level only. Expect a few metres of error in open country and more on "
                    "steep side slopes, in woodland and near structures. Not for design: use LiDAR or "
                    "a ground survey for that.",
    }
    stem = os.path.join(out_dir, "A1_Harare_Chirundu")
    write_kmz(stem + "_terrain.kmz", cl, z, g, cls, contours, events, steep, towns, low_conf)
    write_plan_dxf(stem + "_plan_contours_UTM35S.dxf", cl, z, cls, contours, events, steep)
    write_long_section_dxf(stem + "_long_section.dxf", cl, z_cop, z, g, events, steep, towns)
    align, sta = civil3d_alignment(cl)
    align_len, n_lines = write_landxml(stem + "_Civil3D_alignment_profile.xml", align, sta, z, z_cop)
    write_surface_tif(stem + "_Civil3D_surface_DEM_UTM35S.tif", cop, cop_t, corridor_polygon(cl))
    write_excel(stem + "_profile_and_steep_sections.xlsx", cl, sta, z_cop, z_srtm, z, g, sens, events, steep,
                towns, crossings, low_conf, meta)
    zoom = plot_profile(stem + "_profile.png", cl, z_cop, z_srtm, z, g, events, steep, towns, low_conf)
    plot_map(stem + "_steep_sections_map.png", cop, cop_t, cl, g, towns, steep, zoom)
    summary = {"length_km": round(cl["ch"][-1] / 1000, 2), "bridges": len(cl["bridges"]),
               "events": len(events), "steep_sections": len(steep), "contours": len(contours),
               "towns": [(t["name"], round(t["ch"] / 1000, 1)) for t in towns],
               "elev_start": round(float(z[0])), "elev_end": round(float(z[-1])),
               "max_raw_drop": round(max((e["max_drop_m"] for e in events), default=0), 1),
               "landxml_alignment_m": round(align_len, 1), "landxml_lines": n_lines}
    with open(os.path.join(cache, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
