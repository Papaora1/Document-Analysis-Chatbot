"""Download Surveyor-General cadastral data for Mohlakeng (Rand West City, Gauteng).

Source: National Cadastral Layer (custodian: Chief Surveyor-General), published by
DFFE at https://dffeportal.environment.gov.za/hosting/rest/services/CSG_Cadaster/CSG_Cadastral_Data/MapServer

Outputs (written to the output directory, default: this script's folder):
    Mohlakeng_cadastre.kmz             Google Earth file (erven, public places, farm portions)
    Mohlakeng_erven_list.xlsx          Spreadsheet of every erf with area and centroid
    Mohlakeng_cadastre_shapefiles.zip  Shapefiles in WGS84 (lat/long) and Lo27 (Hartebeesthoek94)
    Mohlakeng_cadastre.gpkg            All layers in one GeoPackage (WGS84), for QGIS/ArcGIS

Usage:
    pip install geopandas pyogrio openpyxl
    python fetch_mohlakeng_cadastre.py [output_dir]
"""

import datetime
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from xml.sax.saxutils import escape

import geopandas as gpd
import pandas as pd

SERVICE = ("https://dffeportal.environment.gov.za/hosting/rest/services/"
           "CSG_Cadaster/CSG_Cadastral_Data/MapServer")
TOWNSHIP = "MOHLAKENG"
PAGE_SIZE = 1000
WGS84 = "EPSG:4326"
LO27 = "EPSG:2052"  # Hartebeesthoek94 / Lo27, the South African survey system for this area

# Raw SG fields that are internal to the service or only drive map labels. GEOM_AREA is
# dropped because for unregistered (LSTATUS 'S') erven it is ~12% too large, apparently
# computed from degrees at the equatorial scale; AREA_M2 is recomputed from the polygon.
DROP_FIELDS = ["GID", "TAG_X", "TAG_Y", "TAG_SIZE", "TAG_ANGLE", "TAG_JUST", "TAG_VALUE",
               "COMMENTS", "Shape.STArea()", "Shape.STLength()", "GIS_Areas", "GEOM_AREA",
               "FARMNAME_EXTENDED"]


def query(layer_id, params):
    url = f"{SERVICE}/{layer_id}/query?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                data = json.load(resp)
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))


def fetch_layer(layer_id, where, envelope=None):
    """Fetch every feature matching `where` (and optionally a lon/lat envelope), paging past the 1000 limit."""
    # The service rejects f=geojson, so pages come back as Esri JSON and GDAL converts them.
    params = {"where": where, "outFields": "*", "outSR": 4326, "orderByFields": "OBJECTID",
              "resultRecordCount": PAGE_SIZE, "f": "json"}
    if envelope:
        params.update(geometry=",".join(map(str, envelope)), geometryType="esriGeometryEnvelope",
                      inSR=4326, spatialRel="esriSpatialRelIntersects")
    expected = query(layer_id, {**params, "returnCountOnly": "true"})["count"]

    collection, offset = None, 0
    while offset < expected:
        page = query(layer_id, {**params, "resultOffset": offset})
        if not page["features"]:
            break
        if collection is None:
            collection = page
        else:
            collection["features"].extend(page["features"])
        offset += len(page["features"])
        print(f"  layer {layer_id}: {offset}/{expected}")
    if offset != expected:
        raise RuntimeError(f"layer {layer_id}: expected {expected} features, got {offset}")

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "features.json")
        with open(path, "w") as f:
            json.dump(collection, f)
        gdf = gpd.read_file(path, engine="pyogrio").set_crs(WGS84, allow_override=True)
    gdf = gdf.drop(columns=[c for c in DROP_FIELDS if c in gdf.columns])
    if "DATE_STAMP" in gdf.columns:
        gdf["DATE_STAMP"] = pd.to_datetime(gdf["DATE_STAMP"]).dt.date.astype("string")
    for col in gdf.columns:
        if col != "geometry" and (gdf[col].dtype == object or pd.api.types.is_string_dtype(gdf[col])):
            gdf[col] = gdf[col].astype("string").str.strip()
    gdf["AREA_M2"] = gdf.to_crs(LO27).area.round(1)
    return gdf


def add_centroids(gdf):
    pts = gdf.to_crs(LO27).representative_point().to_crs(WGS84)
    gdf["LAT"] = pts.y.round(7)
    gdf["LON"] = pts.x.round(7)
    return gdf


def erf_label(row):
    label = f"Erf {row['PARCEL_NO']}"
    if row.get("PORTION"):
        label += f" Ptn {row['PORTION']}"
    return label


def farm_label(row):
    name = f"{row['FARMNAME']} {row['PARCEL_NO']}-{row['MAJ_REGION']}"
    return f"Ptn {row['PORTION']} of {name}" if row["PORTION"] else f"RE/{name}"


def kml_coords(ring):
    return " ".join(f"{x:.7f},{y:.7f}" for x, y in ring.coords)


def kml_polygon(poly):
    inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{kml_coords(r)}</coordinates>"
                    f"</LinearRing></innerBoundaryIs>" for r in poly.interiors)
    return (f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{kml_coords(poly.exterior)}"
            f"</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>")


def kml_folder(name, gdf, label_fn, style, fields):
    marks = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        rows = "".join(f"<tr><td>{escape(f)}</td><td>{escape(str(row[f]))}</td></tr>"
                       for f in fields if f in row and pd.notna(row[f]))
        marks.append(
            f"<Placemark><name>{escape(label_fn(row))}</name><styleUrl>#{style}</styleUrl>"
            f"<description><![CDATA[<table>{rows}</table>]]></description>"
            f"<MultiGeometry>{''.join(kml_polygon(p) for p in polys)}</MultiGeometry></Placemark>")
    return f"<Folder><name>{escape(name)}</name>{''.join(marks)}</Folder>"


def write_kmz(path, layers):
    styles = (
        '<Style id="erf"><LineStyle><color>ff00ffff</color><width>1</width></LineStyle>'
        '<PolyStyle><fill>0</fill></PolyStyle></Style>'
        '<Style id="public"><LineStyle><color>ff00ff00</color><width>1.5</width></LineStyle>'
        '<PolyStyle><color>4000ff00</color></PolyStyle></Style>'
        '<Style id="farm"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle>'
        '<PolyStyle><fill>0</fill></PolyStyle></Style>')
    body = "".join(kml_folder(*layer) for layer in layers)
    kml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>Mohlakeng cadastre (SG data, downloaded {datetime.date.today()})</name>'
           f'{styles}{body}</Document></kml>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)


def write_shapefiles(path, layers):
    with tempfile.TemporaryDirectory() as tmp:
        for folder, crs in (("WGS84_latlong", WGS84), ("Lo27_Hartebeesthoek94", LO27)):
            os.makedirs(os.path.join(tmp, folder))
            for name, gdf in layers.items():
                gdf.to_crs(crs).to_file(os.path.join(tmp, folder, f"{name}.shp"), engine="pyogrio")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(tmp):
                for f in sorted(files):
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, tmp))


def write_excel(path, erven, public, farms):
    def table(gdf, columns):
        out = pd.DataFrame(gdf.drop(columns="geometry"))
        return out[[c for c in columns if c in out.columns]].rename(columns=COLUMN_NAMES)

    parcel_cols = ["PARCEL_NO", "PORTION", "MIN_REGION", "MIN_CODE", "MAJ_REGION", "ID", "PRCL_KEY",
                   "DSG_NO", "SR_NO", "LSTATUS", "WSTATUS", "AREA_M2", "LAT", "LON", "DATE_STAMP"]
    farm_cols = ["FARMNAME", "PARCEL_NO", "PORTION", "MAJ_REGION", "ID", "PRCL_KEY", "DSG_NO",
                 "SR_NO", "LSTATUS", "WSTATUS", "AREA_M2", "LAT", "LON", "DATE_STAMP"]
    about = pd.DataFrame({"Item": [
        "Area", "Source", "Custodian", "Downloaded", "Erven", "Public places",
        "Farm portions (within Mohlakeng extent)", "Area (m²)", "LAT / LON",
        "Note"], "Value": [
        "Mohlakeng township (SG minor region T0IQ0579), Rand West City LM, Gauteng",
        SERVICE, "Chief Surveyor-General (CSG)", str(datetime.date.today()),
        len(erven), len(public), len(farms),
        "Calculated from the polygon in Lo27; the registered extent on the SG diagram is authoritative",
        "A point inside each parcel (WGS84)",
        "Status codes (LSTATUS/WSTATUS) are as published by the SG. For legal boundaries, use the "
        "SG diagram/general plan and a registered land surveyor."]})
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        about.to_excel(xl, sheet_name="About", index=False)
        table(erven.sort_values(["PARCEL_NO", "PORTION"]), parcel_cols).to_excel(
            xl, sheet_name="Erven", index=False)
        table(public.sort_values(["PARCEL_NO", "PORTION"]), parcel_cols).to_excel(
            xl, sheet_name="Public places", index=False)
        table(farms.sort_values(["PARCEL_NO", "PORTION"]), farm_cols).to_excel(
            xl, sheet_name="Farm portions", index=False)
        for ws in xl.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 80)


COLUMN_NAMES = {
    "PARCEL_NO": "Erf / parcel no", "PORTION": "Portion", "MIN_REGION": "Township",
    "MIN_CODE": "Township code", "MAJ_REGION": "Registration division", "ID": "SG 21-digit key",
    "PRCL_KEY": "Parcel key", "DSG_NO": "SG diagram no", "SR_NO": "Survey record no",
    "LSTATUS": "LSTATUS", "WSTATUS": "WSTATUS", "AREA_M2": "Area (m²)", "LAT": "Latitude",
    "LON": "Longitude", "DATE_STAMP": "SG date stamp", "FARMNAME": "Farm name"}


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    print("Erven...")
    erven = add_centroids(fetch_layer(2, f"MIN_REGION='{TOWNSHIP}'"))
    print("Public places...")
    public = add_centroids(fetch_layer(4, f"MIN_REGION='{TOWNSHIP}'"))
    xmin, ymin, xmax, ymax = erven.total_bounds
    print("Farm portions...")
    farms = add_centroids(fetch_layer(1, "1=1", (xmin, ymin, xmax, ymax)))

    layers = {"Mohlakeng_erven": erven, "Mohlakeng_public_places": public,
              "Mohlakeng_farm_portions": farms}
    gpkg = os.path.join(out_dir, "Mohlakeng_cadastre.gpkg")
    if os.path.exists(gpkg):
        os.remove(gpkg)
    for name, gdf in layers.items():
        gdf.to_file(gpkg, layer=name, engine="pyogrio")
    write_shapefiles(os.path.join(out_dir, "Mohlakeng_cadastre_shapefiles.zip"), layers)
    write_excel(os.path.join(out_dir, "Mohlakeng_erven_list.xlsx"), erven, public, farms)

    erf_fields = ["PARCEL_NO", "PORTION", "MIN_REGION", "ID", "DSG_NO", "AREA_M2", "LSTATUS",
                  "WSTATUS", "DATE_STAMP"]
    farm_fields = ["FARMNAME", "PARCEL_NO", "PORTION", "MAJ_REGION", "ID", "DSG_NO", "AREA_M2"]
    write_kmz(os.path.join(out_dir, "Mohlakeng_cadastre.kmz"), [
        ("Farm portions", farms, farm_label, "farm", farm_fields),
        ("Public places", public, erf_label, "public", erf_fields),
        ("Erven", erven, erf_label, "erf", erf_fields)])
    print(f"Done: {len(erven)} erven, {len(public)} public places, {len(farms)} farm portions -> {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
