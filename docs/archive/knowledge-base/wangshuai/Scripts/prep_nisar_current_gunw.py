#!/usr/bin/env python3
"""Compatibility wrapper for MintPy prep_nisar on current ISCE3 GUNW outputs."""

from __future__ import annotations

import glob
import os
import re
import sys
import tempfile
from pathlib import Path

from osgeo import gdal
from mintpy.cli.prep_nisar import cmd_line_parse
import mintpy.prep_nisar as prep_nisar


DATE_PAIR_RE = re.compile(r"(?P<d1>\d{8})_(?P<d2>\d{8})")


def get_date_pairs(filenames: list[str]) -> list[str]:
    date12_list: list[str] = []
    for fname in filenames:
        stem = Path(fname).stem
        match = DATE_PAIR_RE.search(stem)
        if not match:
            raise ValueError(f"Cannot infer date pair from filename: {fname}")
        date12_list.append(f"{match.group('d1')}_{match.group('d2')}")
    return date12_list


def update_dataset_paths(polarization: str = "HH") -> None:
    for key, value in list(prep_nisar.DATASETS.items()):
        if value and "POL" in value:
            prep_nisar.DATASETS[key] = value.replace("POL", polarization)


def compute_common_grid(
    input_files: list[str], bbox: tuple[float, float, float, float] | None = None
) -> tuple[prep_nisar.np.ndarray, prep_nisar.np.ndarray, tuple[float, float, float, float]]:
    west_list: list[float] = []
    east_list: list[float] = []
    south_list: list[float] = []
    north_list: list[float] = []
    x_steps: list[float] = []
    y_steps: list[float] = []

    for file in input_files:
        with prep_nisar.h5py.File(file, "r") as ds:
            xcoord = ds[prep_nisar.DATASETS["xcoord"]][:]
            ycoord = ds[prep_nisar.DATASETS["ycoord"]][:]
            west_list.append(float(prep_nisar.np.min(xcoord)))
            east_list.append(float(prep_nisar.np.max(xcoord)))
            south_list.append(float(prep_nisar.np.min(ycoord)))
            north_list.append(float(prep_nisar.np.max(ycoord)))
            x_steps.append(float(ds[prep_nisar.DATASETS["xSpacing"]][()]))
            y_steps.append(float(ds[prep_nisar.DATASETS["ySpacing"]][()]))

    west = max(west_list)
    east = min(east_list)
    south = max(south_list)
    north = min(north_list)
    if bbox is not None:
        west = max(west, bbox[0])
        south = max(south, bbox[1])
        east = min(east, bbox[2])
        north = min(north, bbox[3])
    if west >= east or south >= north:
        raise ValueError("No common overlap exists among the selected GUNW files")

    x_step = min(abs(step) for step in x_steps)
    y_step = min(abs(step) for step in y_steps)
    width = int(prep_nisar.np.floor((east - west) / x_step)) + 1
    length = int(prep_nisar.np.floor((north - south) / y_step)) + 1
    if width < 2 or length < 2:
        raise ValueError("Common overlap is too small after grid alignment")

    xcoord_common = west + prep_nisar.np.arange(width) * x_step
    ycoord_common = north - prep_nisar.np.arange(length) * y_step
    bounds = (
        float(xcoord_common[0]),
        float(ycoord_common[-1]),
        float(xcoord_common[-1]),
        float(ycoord_common[0]),
    )
    return xcoord_common, ycoord_common, bounds


def resample_to_common_grid(
    data: prep_nisar.np.ndarray,
    src_xcoord: prep_nisar.np.ndarray,
    src_ycoord: prep_nisar.np.ndarray,
    dst_xcoord: prep_nisar.np.ndarray,
    dst_ycoord: prep_nisar.np.ndarray,
    method: str = "nearest",
    fill_value: float = prep_nisar.np.nan,
) -> prep_nisar.np.ndarray:
    dst_y_2d, dst_x_2d = prep_nisar.np.meshgrid(dst_ycoord, dst_xcoord, indexing="ij")
    points = prep_nisar.np.stack((dst_y_2d.flatten(), dst_x_2d.flatten()), axis=-1)
    interpolator = prep_nisar.RegularGridInterpolator(
        (src_ycoord, src_xcoord),
        data,
        method=method,
        bounds_error=False,
        fill_value=fill_value,
    )
    return interpolator(points).reshape(len(dst_ycoord), len(dst_xcoord))


def extract_common_grid_metadata(
    input_files: list[str],
    bbox: tuple[float, float, float, float] | None = None,
    polarization: str = "HH",
) -> tuple[dict[str, object], prep_nisar.np.ndarray, prep_nisar.np.ndarray]:
    update_dataset_paths(polarization)
    meta_file = input_files[0]
    meta: dict[str, object] = {}

    with prep_nisar.h5py.File(meta_file, "r") as ds:
        pixel_height = float(ds[prep_nisar.DATASETS["ySpacing"]][()])
        pixel_width = float(ds[prep_nisar.DATASETS["xSpacing"]][()])
        meta["EPSG"] = int(ds[prep_nisar.DATASETS["epsg"]][()])
        meta["WAVELENGTH"] = (
            prep_nisar.SPEED_OF_LIGHT / ds[prep_nisar.PROCESSINFO["centerFrequency"]][()]
        )
        meta["ORBIT_DIRECTION"] = ds[prep_nisar.PROCESSINFO["orbit_direction"]][()].decode("utf-8")
        meta["POLARIZATION"] = polarization
        meta["ALOOKS"] = ds[prep_nisar.DATASETS["azimuth_look"]][()]
        meta["RLOOKS"] = ds[prep_nisar.DATASETS["range_look"]][()]
        meta["PLATFORM"] = ds[prep_nisar.PROCESSINFO["platform"]][()].decode("utf-8")
        meta["STARTING_RANGE"] = float(
            prep_nisar.np.nanmin(ds[prep_nisar.PROCESSINFO["rdr_slant_range"]][()])
        )
        start_time = prep_nisar.datetime.datetime.strptime(
            ds[prep_nisar.PROCESSINFO["start_time"]][()].decode("utf-8")[0:26],
            "%Y-%m-%dT%H:%M:%S.%f",
        )
        end_time = prep_nisar.datetime.datetime.strptime(
            ds[prep_nisar.PROCESSINFO["end_time"]][()].decode("utf-8")[0:26],
            "%Y-%m-%dT%H:%M:%S.%f",
        )

    t_mid = start_time + (end_time - start_time) / 2.0
    meta["CENTER_LINE_UTC"] = (
        t_mid - prep_nisar.datetime.datetime(t_mid.year, t_mid.month, t_mid.day)
    ).total_seconds()
    meta["HEIGHT"] = 747000

    xcoord_common, ycoord_common, bounds = compute_common_grid(input_files, bbox)
    meta["X_FIRST"] = float(xcoord_common[0])
    meta["Y_FIRST"] = float(ycoord_common[0])
    meta["X_STEP"] = pixel_width
    meta["Y_STEP"] = pixel_height
    meta["WIDTH"] = len(xcoord_common)
    meta["LENGTH"] = len(ycoord_common)
    meta["bbox"] = ",".join(str(b) for b in bounds)
    if meta["EPSG"] == 4326:
        meta["X_UNIT"] = meta["Y_UNIT"] = "degree"
    else:
        meta["X_UNIT"] = meta["Y_UNIT"] = "meters"
        epsg = str(meta["EPSG"])
        meta["UTM_ZONE"] = epsg[3:] + ("N" if epsg.startswith("326") else "S")
    meta["EARTH_RADIUS"] = prep_nisar.EARTH_RADIUS
    meta["RANGE_PIXEL_SIZE"] = abs(pixel_width)
    meta["AZIMUTH_PIXEL_SIZE"] = abs(pixel_height)
    return meta, xcoord_common, ycoord_common


def prepare_geometry_common_grid(
    outfile: str,
    meta_file: str,
    metadata: dict[str, object],
    dem_file: str,
    mask_file: str | None,
    xcoord_common: prep_nisar.np.ndarray,
    ycoord_common: prep_nisar.np.ndarray,
) -> dict[str, object]:
    print("-" * 50)
    print(f"preparing geometry file: {outfile}")

    dem_subset_array, slant_range, incidence_angle, mask = read_and_interpolate_geometry_on_grid(
        meta_file=meta_file,
        dem_file=dem_file,
        mask_file=mask_file,
        xcoord_common=xcoord_common,
        ycoord_common=ycoord_common,
    )

    meta = dict(metadata)
    meta["FILE_TYPE"] = "geometry"
    meta["STARTING_RANGE"] = float(prep_nisar.np.nanmin(slant_range))
    ds_name_dict = {
        "height": [prep_nisar.np.float32, dem_subset_array.shape, dem_subset_array],
        "incidenceAngle": [prep_nisar.np.float32, incidence_angle.shape, incidence_angle],
        "slantRangeDistance": [prep_nisar.np.float32, slant_range.shape, slant_range],
    }
    if mask_file:
        ds_name_dict["waterMask"] = [prep_nisar.np.bool_, mask.shape, mask.astype(bool)]
    prep_nisar.writefile.layout_hdf5(outfile, ds_name_dict, metadata=meta)
    return meta


def prepare_stack_common_grid(
    outfile: str,
    input_files: list[str],
    metadata: dict[str, object],
    date12_list: list[str],
    xcoord_common: prep_nisar.np.ndarray,
    ycoord_common: prep_nisar.np.ndarray,
) -> str:
    print("-" * 50)
    print(f"preparing ifgramStack file: {outfile}")
    num_pair = len(input_files)
    rows = len(ycoord_common)
    cols = len(xcoord_common)
    print(f"number of inputs/unwrapped interferograms: {num_pair}")

    date12_arr = prep_nisar.np.array([x.split("_") for x in date12_list], dtype=prep_nisar.np.bytes_)
    drop_ifgram = prep_nisar.np.ones(num_pair, dtype=prep_nisar.np.bool_)
    ds_name_dict = {
        "date": [date12_arr.dtype, (num_pair, 2), date12_arr],
        "bperp": [prep_nisar.np.float32, (num_pair,), prep_nisar.np.zeros(num_pair, dtype=prep_nisar.np.float32)],
        "dropIfgram": [prep_nisar.np.bool_, (num_pair,), drop_ifgram],
        "unwrapPhase": [prep_nisar.np.float32, (num_pair, rows, cols), None],
        "coherence": [prep_nisar.np.float32, (num_pair, rows, cols), None],
        "connectComponent": [prep_nisar.np.float32, (num_pair, rows, cols), None],
    }
    meta = dict(metadata)
    meta["FILE_TYPE"] = "ifgramStack"
    prep_nisar.writefile.layout_hdf5(outfile, ds_name_dict, metadata=meta)

    print(f"writing data to HDF5 file {outfile} with a mode ...")
    with prep_nisar.h5py.File(outfile, "a") as f:
        prog_bar = prep_nisar.ptime.progressBar(maxValue=num_pair)
        for i, file in enumerate(input_files):
            with prep_nisar.h5py.File(file, "r") as ds:
                src_xcoord = ds[prep_nisar.DATASETS["xcoord"]][:]
                src_ycoord = ds[prep_nisar.DATASETS["ycoord"]][:]
                unw_data = ds[prep_nisar.DATASETS["unw"]][:]
                cor_data = ds[prep_nisar.DATASETS["cor"]][:]
                conn_comp = ds[prep_nisar.DATASETS["connComp"]][:]
                pbase = float(prep_nisar.np.nanmean(ds[prep_nisar.PROCESSINFO["bperp"]][()]))

            unw_resampled = resample_to_common_grid(
                unw_data,
                src_xcoord,
                src_ycoord,
                xcoord_common,
                ycoord_common,
                method="nearest",
            ).astype(prep_nisar.np.float32)
            cor_resampled = resample_to_common_grid(
                cor_data,
                src_xcoord,
                src_ycoord,
                xcoord_common,
                ycoord_common,
                method="nearest",
            ).astype(prep_nisar.np.float32)
            conn_resampled = resample_to_common_grid(
                conn_comp.astype(prep_nisar.np.float32),
                src_xcoord,
                src_ycoord,
                xcoord_common,
                ycoord_common,
                method="nearest",
            ).astype(prep_nisar.np.float32)
            conn_resampled[conn_resampled > 254] = prep_nisar.np.nan

            f["unwrapPhase"][i] = unw_resampled
            f["coherence"][i] = cor_resampled
            f["connectComponent"][i] = conn_resampled
            f["bperp"][i] = pbase
            prog_bar.update(i + 1, suffix=date12_list[i])
        prog_bar.close()

    print(f"finished writing to HDF5 file: {outfile}")
    return outfile


def read_and_interpolate_geometry_on_grid(
    meta_file,
    dem_file,
    xcoord_common,
    ycoord_common,
    mask_file=None,
):
    dem_dataset = gdal.Open(dem_file, gdal.GA_ReadOnly)
    proj = gdal.osr.SpatialReference(wkt=dem_dataset.GetProjection())
    dem_src_epsg = int(proj.GetAttrValue("AUTHORITY", 1))
    del dem_dataset

    rdr_coords = {}

    with prep_nisar.h5py.File(meta_file, "r") as ds:
        dst_epsg = ds[prep_nisar.DATASETS["epsg"]][()]
        rdr_coords["xcoord_radar_grid"] = ds[prep_nisar.PROCESSINFO["rdr_xcoord"]][()]
        rdr_coords["ycoord_radar_grid"] = ds[prep_nisar.PROCESSINFO["rdr_ycoord"]][()]
        rdr_coords["height_radar_grid"] = ds[prep_nisar.PROCESSINFO["rdr_height"]][()]
        rdr_coords["slant_range"] = ds[prep_nisar.PROCESSINFO["rdr_slant_range"]][()]
        rdr_coords["perp_baseline"] = ds[prep_nisar.PROCESSINFO["bperp"]][()]
        rdr_coords["incidence_angle"] = ds[prep_nisar.PROCESSINFO["rdr_incidence"]][()]

    subset_rows = len(ycoord_common)
    subset_cols = len(xcoord_common)
    y_2d, x_2d = prep_nisar.np.meshgrid(ycoord_common, xcoord_common, indexing="ij")
    bounds = (
        float(xcoord_common[0]),
        float(ycoord_common[-1]),
        float(xcoord_common[-1]),
        float(ycoord_common[0]),
    )
    output_projection = f"EPSG:{dst_epsg}"
    input_projection = f"EPSG:{dem_src_epsg}"

    with tempfile.TemporaryDirectory(prefix="mintpy_nisar_") as tmp_dir:
        output_dem = os.path.join(tmp_dir, "dem_transformed.tif")
        gdal.Warp(
            output_dem,
            dem_file,
            outputBounds=bounds,
            format="GTiff",
            srcSRS=input_projection,
            dstSRS=output_projection,
            resampleAlg=gdal.GRA_Bilinear,
            width=subset_cols,
            height=subset_rows,
            creationOptions=["COMPRESS=DEFLATE"],
        )
        dem_subset_array = gdal.Open(output_dem, gdal.GA_ReadOnly).ReadAsArray()

        slant_range, incidence_angle = interpolate_geometry(
            x_2d, y_2d, dem_subset_array, rdr_coords
        )

        if mask_file in ["auto", "None", None]:
            print("*** No mask was found ***")
            mask_subset_array = prep_nisar.np.ones(dem_subset_array.shape, dtype="byte")
        else:
            mask_dataset = gdal.Open(mask_file, gdal.GA_ReadOnly)
            proj = gdal.osr.SpatialReference(wkt=mask_dataset.GetProjection())
            mask_src_epsg = int(proj.GetAttrValue("AUTHORITY", 1))
            del mask_dataset

            output_mask = os.path.join(tmp_dir, "mask_transformed.tif")
            gdal.Warp(
                output_mask,
                mask_file,
                outputBounds=bounds,
                format="GTiff",
                srcSRS=f"EPSG:{mask_src_epsg}",
                dstSRS=output_projection,
                resampleAlg=gdal.GRA_NearestNeighbour,
                width=subset_cols,
                height=subset_rows,
                creationOptions=["COMPRESS=DEFLATE"],
            )
            mask_subset_array = gdal.Open(output_mask, gdal.GA_ReadOnly).ReadAsArray()

    return dem_subset_array, slant_range, incidence_angle, mask_subset_array


def interpolate_geometry(x_2d, y_2d, dem, rdr_coords):
    points = prep_nisar.np.stack((dem.flatten(), y_2d.flatten(), x_2d.flatten()), axis=-1)
    length, width = y_2d.shape

    interpolator = prep_nisar.RegularGridInterpolator(
        (
            rdr_coords["height_radar_grid"],
            rdr_coords["ycoord_radar_grid"],
            rdr_coords["xcoord_radar_grid"],
        ),
        rdr_coords["slant_range"],
        method="linear",
        bounds_error=False,
        fill_value=prep_nisar.np.nan,
    )
    interpolated_slant_range = interpolator(points)

    interpolator = prep_nisar.RegularGridInterpolator(
        (
            rdr_coords["height_radar_grid"],
            rdr_coords["ycoord_radar_grid"],
            rdr_coords["xcoord_radar_grid"],
        ),
        rdr_coords["incidence_angle"],
        method="linear",
        bounds_error=False,
        fill_value=prep_nisar.np.nan,
    )
    interpolated_incidence_angle = interpolator(points)

    return (
        interpolated_slant_range.reshape(length, width),
        interpolated_incidence_angle.reshape(length, width),
    )


def main(iargs: list[str] | None = None) -> int:
    # Current ISCE3 GUNW products store radar-grid slant range as separate
    # reference/secondary datasets instead of the older generic slantRange name.
    prep_nisar.PROCESSINFO['rdr_slant_range'] = (
        "science/LSAR/GUNW/metadata/radarGrid/referenceSlantRange"
    )
    inps = cmd_line_parse(iargs)
    input_files = sorted(glob.glob(inps.input_glob))
    if len(input_files) == 0:
        raise FileNotFoundError(f"No GUNW files matched: {inps.input_glob}")

    bbox = None
    if inps.subset_lat:
        bbox = (inps.subset_lon[0], inps.subset_lat[0], inps.subset_lon[1], inps.subset_lat[1])

    metadata, xcoord_common, ycoord_common = extract_common_grid_metadata(input_files, bbox=bbox)
    stack_file = os.path.join(inps.out_dir, "inputs/ifgramStack.h5")
    geometry_file = os.path.join(inps.out_dir, "inputs/geometryGeo.h5")
    date12_list = get_date_pairs(input_files)

    metadata = prepare_geometry_common_grid(
        outfile=geometry_file,
        meta_file=input_files[0],
        metadata=metadata,
        dem_file=inps.dem_file,
        mask_file=inps.mask_file,
        xcoord_common=xcoord_common,
        ycoord_common=ycoord_common,
    )
    prepare_stack_common_grid(
        outfile=stack_file,
        input_files=input_files,
        metadata=metadata,
        date12_list=date12_list,
        xcoord_common=xcoord_common,
        ycoord_common=ycoord_common,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
