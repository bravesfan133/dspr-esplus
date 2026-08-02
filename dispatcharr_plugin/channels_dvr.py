"""Channels DVR REST client used to refresh M3U playlist sources and XMLTV guides."""
import logging
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
M3U_DEVICE_PREFIX = "M3U"


def normalize_base_url(base_url: str) -> str:
    """Ensure the base URL has a scheme and no trailing slash."""
    url = (base_url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/")


def derive_epg_lineup_name(m3u_source_name: str) -> str:
    """Channels DVR names the XMLTV lineup for an M3U source XMLTV-<name>."""
    return f"XMLTV-{m3u_source_name.strip()}"


def _parse_lineups(payload) -> tuple[list[str], dict]:
    """`GET /dvr/lineups` returns a dict mapping device IDs to lineup names.

    Returns (lineup_names, device_to_lineup).
    """
    if isinstance(payload, dict):
        names = set()
        mapping = {}
        for key, value in payload.items():
            if isinstance(value, str) and value:
                names.add(value)
                mapping[str(key)] = value
        return sorted(names), mapping
    if isinstance(payload, list):
        return sorted(str(item) for item in payload if str(item)), {}
    return [], {}


def list_sources(base_url: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """List M3U sources and EPG lineups on a Channels DVR server.

    Returns:
        {
          "m3u_sources": [{"name": str, "device_id": str}],
          "epg_lineups": [str, ...],
          "device_to_lineup": {device_id: lineup_name, ...},
        }
    """
    import requests

    base_url = normalize_base_url(base_url)
    m3u_sources: list[dict] = []
    epg_lineups: list[str] = []
    device_to_lineup: dict = {}

    try:
        resp = requests.get(f"{base_url}/devices", timeout=timeout)
        resp.raise_for_status()
        devices = resp.json()
        if isinstance(devices, dict):
            devices = devices.get("Devices") or devices.get("devices") or []
        for device in devices or []:
            if not isinstance(device, dict):
                continue
            device_id = str(device.get("DeviceID") or device.get("device_id") or "")
            if not device_id.upper().startswith(M3U_DEVICE_PREFIX):
                continue
            name = (
                str(device.get("FriendlyName") or device.get("friendly_name") or "")
                .strip()
            )
            if not name:
                name = device_id[4:]
            m3u_sources.append({"name": name, "device_id": device_id})
    except Exception as e:
        logger.warning(f"Failed to list Channels DVR M3U sources: {e}")

    try:
        resp = requests.get(f"{base_url}/dvr/lineups", timeout=timeout)
        resp.raise_for_status()
        epg_lineups, device_to_lineup = _parse_lineups(resp.json())
    except Exception as e:
        logger.warning(f"Failed to list Channels DVR EPG lineups: {e}")

    return {
        "m3u_sources": m3u_sources,
        "epg_lineups": epg_lineups,
        "device_to_lineup": device_to_lineup,
    }


def is_reachable(base_url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[str]:
    """Return None when reachable, else an error message string."""
    import requests

    base_url = normalize_base_url(base_url)
    if not base_url:
        return "Channels DVR base URL is empty"
    try:
        resp = requests.get(f"{base_url}/status", timeout=timeout)
        resp.raise_for_status()
        return None
    except Exception as e:
        return str(e)


def refresh_m3u_source(
    base_url: str,
    source_name: str,
    device_id: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """POST the Channels DVR refresh endpoint for an M3U source.

    Retries with the raw device id if the friendly-name URL 404s.
    """
    import requests

    base_url = normalize_base_url(base_url)
    source_name = (source_name or "").strip()
    if not source_name:
        logger.warning("No Channels DVR M3U source selected — skipping refresh")
        return False

    names = [source_name]
    if device_id and device_id not in names:
        names.append(device_id)

    for name in names:
        url = f"{base_url}/providers/m3u/sources/{quote(name)}/refresh"
        try:
            resp = requests.post(url, timeout=timeout)
            if resp.status_code == 404 and len(names) > 1:
                logger.warning(f"Channels DVR M3U refresh 404 for '{name}': {url}")
                continue
            resp.raise_for_status()
            logger.info(f"Channels DVR M3U refresh triggered for '{source_name}': POST {url} -> {resp.status_code}")
            return True
        except Exception as e:
            logger.warning(f"Channels DVR M3U refresh failed for '{name}': {e} (POST {url})")
            if len(names) == 1 or name == names[-1]:
                return False
    return False


def refresh_and_report(
    base_url: str,
    source_name: str,
    lineup_name: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Perform the real M3U POST and EPG PUT refresh and report each URL + status.

    Returns {"status": "ok"|"error", "details": [...], "message": str}.
    """
    import requests

    base_url = normalize_base_url(base_url)
    source_name = (source_name or "").strip()
    lineup_name = (lineup_name or "").strip() or derive_epg_lineup_name(source_name)

    details = []
    if not source_name:
        return {
            "status": "error",
            "details": details,
            "message": "No Channels DVR M3U source selected",
        }

    m3u_url = f"{base_url}/providers/m3u/sources/{quote(source_name)}/refresh"
    try:
        resp = requests.post(m3u_url, timeout=timeout)
        resp.raise_for_status()
        details.append(f"POST {m3u_url} -> {resp.status_code}")
    except Exception as e:
        details.append(f"POST {m3u_url} -> ERROR: {e}")

    epg_url = f"{base_url}/dvr/lineups/{quote(lineup_name)}"
    try:
        resp = requests.put(epg_url, timeout=timeout)
        resp.raise_for_status()
        details.append(f"PUT {epg_url} -> {resp.status_code}")
    except Exception as e:
        details.append(f"PUT {epg_url} -> ERROR: {e}")

    errors = [d for d in details if "ERROR" in d]
    if errors:
        return {
            "status": "error",
            "details": details,
            "message": "; ".join(errors),
        }
    return {
        "status": "ok",
        "details": details,
        "message": f"Channels DVR refresh OK: M3U '{source_name}', EPG '{lineup_name}'",
    }


def refresh_epg_lineup(
    base_url: str,
    lineup_name: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """PUT the Channels DVR guide re-download endpoint for an XMLTV lineup."""
    import requests

    base_url = normalize_base_url(base_url)
    lineup_name = (lineup_name or "").strip()
    if not lineup_name:
        logger.warning("No Channels DVR EPG lineup selected — skipping refresh")
        return False

    url = f"{base_url}/dvr/lineups/{quote(lineup_name)}"
    try:
        resp = requests.put(url, timeout=timeout)
        resp.raise_for_status()
        logger.info(f"Channels DVR EPG refresh triggered for '{lineup_name}': PUT {url} -> {resp.status_code}")
        return True
    except Exception as e:
        logger.warning(f"Channels DVR EPG refresh failed for '{lineup_name}': {e} (PUT {url})")
        return False
