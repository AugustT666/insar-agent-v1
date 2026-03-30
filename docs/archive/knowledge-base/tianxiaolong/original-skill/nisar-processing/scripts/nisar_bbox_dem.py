#!/usr/bin/env python3
"""
Extract lon/lat bounds from NISAR RSLC boundingPolygon and
print a DEM download command using ddem.pyc.
"""

import argparse
import re
from pathlib import Path

import h5py


def parse_bounding_polygon(wkt_text):
    coords = re.findall(r"([\-0-9.]+)\s+([\-0-9.]+)\s+([\-0-9.]+)", wkt_text)
    if not coords:
        raise ValueError("Failed to parse boundingPolygon WKT")
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    return min(lons), min(lats), max(lons), max(lats)


def extract_bbox(rslc_path):
    with h5py.File(rslc_path, "r") as h5:
        wkt = h5["/science/LSAR/identification/boundingPolygon"][()].decode()
    return parse_bounding_polygon(wkt)


def main():
    parser = argparse.ArgumentParser(
        description="Compute bbox from RSLCs and suggest DEM download command."
    )
    parser.add_argument(
        "rslc",
        nargs="+",
        help="One or more RSLC .h5 files",
    )
    parser.add_argument(
        "--ddem",
        help="Path to ddem.pyc (optional; prints full command if provided)",
    )
    parser.add_argument(
        "--out",
        help="DEM output path for ddem.pyc (optional)",
    )
    parser.add_argument(
        "--source",
        default="copernicus_30",
        help="DEM source for ddem.pyc (default: copernicus_30)",
    )
    parser.add_argument(
        "--proj-lib",
        help="PROJ_LIB path to avoid GDAL SRS errors (optional)",
    )
    args = parser.parse_args()

    all_min_lon = None
    all_min_lat = None
    all_max_lon = None
    all_max_lat = None

    for path in args.rslc:
        min_lon, min_lat, max_lon, max_lat = extract_bbox(path)
        all_min_lon = min(min_lon, all_min_lon) if all_min_lon is not None else min_lon
        all_min_lat = min(min_lat, all_min_lat) if all_min_lat is not None else min_lat
        all_max_lon = max(max_lon, all_max_lon) if all_max_lon is not None else max_lon
        all_max_lat = max(max_lat, all_max_lat) if all_max_lat is not None else max_lat
        print(f"{Path(path).name}: lon [{min_lon}, {max_lon}] lat [{min_lat}, {max_lat}]")

    print("\nUnion bbox:")
    print(f"  min_lon: {all_min_lon}")
    print(f"  min_lat: {all_min_lat}")
    print(f"  max_lon: {all_max_lon}")
    print(f"  max_lat: {all_max_lat}")

    if args.ddem and args.out:
        proj_prefix = ""
        if args.proj_lib:
            proj_prefix = f'PROJ_LIB="{args.proj_lib}" '
        print("\nSuggested DEM command:")
        print(
            f"{proj_prefix}{args.ddem} --min-lon {all_min_lon} --min-lat {all_min_lat} "
            f"--max-lon {all_max_lon} --max-lat {all_max_lat} --source {args.source} "
            f"-o \"{args.out}\" --overwrite"
        )


if __name__ == "__main__":
    main()
