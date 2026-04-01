from __future__ import annotations

import json
import mimetypes
import re
import urllib.request
import uuid
from pathlib import Path


_ASF_FILES_TO_WKT_URL = "https://api.daac.asf.alaska.edu/services/utils/files_to_wkt"
_WKT_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def _bbox_from_wkt(wkt_text: str) -> tuple[float, float, float, float]:
    coords = _WKT_COORD_RE.findall(wkt_text)
    if not coords:
        raise ValueError(f"No coordinates found in WKT: {wkt_text!r}")
    lons = [float(lon) for lon, _ in coords]
    lats = [float(lat) for _, lat in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _merge_bbox(
    current: tuple[float, float, float, float] | None,
    other: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if current is None:
        return other

    return (
        min(current[0], other[0]),
        min(current[1], other[1]),
        max(current[2], other[2]),
        max(current[3], other[3]),
    )


def _transform_extent_to_wgs84(
    extent: tuple[float, float, float, float],
    transform,
) -> tuple[float, float, float, float]:
    from osgeo import ogr

    min_x, max_x, min_y, max_y = extent
    bounds: tuple[float, float, float, float] | None = None
    for x, y in (
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y),
    ):
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint(x, y)
        point.Transform(transform)
        bounds = _merge_bbox(
            bounds,
            (
                float(point.GetX()),
                float(point.GetY()),
                float(point.GetX()),
                float(point.GetY()),
            ),
        )

    if bounds is None:
        raise RuntimeError("Failed to transform AOI extent to EPSG:4326")
    return bounds


def _resolve_local_bbox(aoi_path: str | Path) -> tuple[float, float, float, float]:
    from osgeo import gdal, ogr, osr

    gdal.UseExceptions()
    ogr.UseExceptions()
    osr.UseExceptions()
    dataset = ogr.Open(str(aoi_path))
    if dataset is None:
        raise RuntimeError(f"OGR could not open AOI file: {aoi_path}")

    if dataset.GetLayerCount() == 0:
        raise RuntimeError(f"AOI file has no readable layers: {aoi_path}")

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    bounds: tuple[float, float, float, float] | None = None
    for layer_index in range(dataset.GetLayerCount()):
        layer = dataset.GetLayerByIndex(layer_index)
        if layer is None:
            continue

        source_srs = layer.GetSpatialRef()
        transform = None
        if source_srs is not None:
            source_srs = source_srs.Clone()
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        source_auth = source_srs.GetAuthorityCode(None) if source_srs is not None else None
        should_transform = (
            source_srs is not None
            and not (bool(source_srs.IsGeographic()) and source_auth == "4326")
            and not bool(source_srs.IsSame(target_srs))
        )
        if should_transform:
            transform = osr.CoordinateTransformation(source_srs, target_srs)

        layer.ResetReading()
        saw_geometry = False
        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geometry = geometry.Clone()
            if transform is not None:
                geometry.Transform(transform)
            min_x, max_x, min_y, max_y = geometry.GetEnvelope()
            bounds = _merge_bbox(
                bounds,
                (float(min_x), float(min_y), float(max_x), float(max_y)),
            )
            saw_geometry = True

        if saw_geometry:
            continue

        extent = layer.GetExtent()
        if extent is None:
            continue

        layer_bounds = (
            float(extent[0]),
            float(extent[2]),
            float(extent[1]),
            float(extent[3]),
        )
        if transform is not None:
            layer_bounds = _transform_extent_to_wgs84(extent, transform)
        bounds = _merge_bbox(bounds, layer_bounds)

    if bounds is None:
        raise RuntimeError(f"AOI extent unavailable: {aoi_path}")
    return bounds


def _resolve_bbox_via_asf(aoi_path: str | Path) -> tuple[float, float, float, float]:
    path = Path(aoi_path)
    payload = path.read_bytes()
    boundary = f"----insar-agent-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8"),
        payload,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    body = b"".join(parts)

    request = urllib.request.Request(
        _ASF_FILES_TO_WKT_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))

    wkt = data.get("parsed wkt")
    if not wkt and isinstance(data.get("wkt"), dict):
        wkt = data["wkt"].get("unwrapped") or data["wkt"].get("wrapped")
    if not wkt:
        raise RuntimeError(f"ASF files_to_wkt returned no usable WKT for {path}")

    return _bbox_from_wkt(wkt)


def resolve_aoi_bbox(aoi_path: str | Path) -> tuple[float, float, float, float]:
    path = Path(aoi_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    try:
        return _resolve_local_bbox(path)
    except Exception as local_exc:
        try:
            return _resolve_bbox_via_asf(path)
        except Exception as asf_exc:
            raise RuntimeError(
                f"Unable to resolve AOI bbox from {path}: local={local_exc}; asf={asf_exc}"
            ) from asf_exc
