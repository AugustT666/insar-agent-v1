"""Catalog discovery for InSAR inputs.

Turns an area of interest plus a time window into a concrete, downloadable
list of granules (NISAR RSLC from NASA CMR, Sentinel-1 bursts from the ASF
SearchAPI). The download itself is handled by the existing
``insar_download_rslc`` / ``insar_download_scene`` tools — this package only
answers "what is available and where do I fetch it".
"""

from insar_agent.discovery import catalog  # noqa: F401
