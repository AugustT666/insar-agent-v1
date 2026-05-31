from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.sentinel.metadata import check_annotation_geolocation_grid


def _validate_safe_annotation_geolocation(
    safe_dir: Path,
    bbox: list[float] | None,
    *,
    require_annotations: bool = False,
) -> None:
    if bbox is None or not safe_dir.is_dir() or safe_dir.suffix.upper() != ".SAFE":
        return
    annotation_dir = safe_dir / "annotation"
    if not annotation_dir.is_dir():
        if require_annotations:
            raise ValueError(f"No Sentinel annotation directory found in synthesized SAFE: {safe_dir}")
        return

    checked = 0
    for annotation_path in annotation_dir.glob("*.xml"):
        result = check_annotation_geolocation_grid(annotation_path.read_text(encoding="utf-8"), bbox)
        if result["status"] == "invalid":
            raise ValueError(f"Invalid Sentinel annotation geolocation in {annotation_path}: {result['reason']}")
        if result["status"] == "ok":
            checked += 1

    if require_annotations and checked == 0:
        raise ValueError(f"No Sentinel annotation geolocation grid could be validated in synthesized SAFE: {safe_dir}")


def _ensure_preview_overlay(safe_dir: Path, bbox: list[float] | None) -> None:
    if bbox is None or not safe_dir.is_dir() or safe_dir.suffix.upper() != ".SAFE":
        return
    overlay_path = safe_dir / "preview" / "map-overlay.kml"
    if overlay_path.exists():
        return

    west, south, east, north = bbox
    kml = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml>
  <Document>
    <Folder>
      <GroundOverlay>
        <name>{safe_dir.name}</name>
        <gxLatLonQuad>
          <coordinates>{west},{south},0 {east},{south},0 {east},{north},0 {west},{north},0</coordinates>
        </gxLatLonQuad>
      </GroundOverlay>
    </Folder>
  </Document>
</kml>
"""
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(kml, encoding="utf-8")
