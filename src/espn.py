import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

ESPN_WATCH_GRAPHQL_URL = "https://watch.graph.api.espn.com/api"
ESPN_WATCH_API_KEY = "0dbf88e8-cc6d-41da-aa83-18b5c630bc5c"

QUERY = (
    'query Airings($day:String,$tz:String!){'
    'airings(day:$day,deviceType:DESKTOP,countryCode:"us",tz:$tz,packages:["ESPN_PLUS"],limit:500){'
    'id name shortName startDateTime endDateTime duration '
    'sport{ name abbreviation } league{ name abbreviation } '
    'category{ name } subcategory{ name } program{ isStudio } image{ url }'
    '}}'
)


def _parse_airing(a: dict) -> Optional[dict]:
    name = a.get("name") or ""
    if not name:
        return None
    try:
        start_dt = datetime.fromisoformat(a["startDateTime"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None

    end_dt = None
    if a.get("endDateTime"):
        try:
            end_dt = datetime.fromisoformat(a["endDateTime"].replace("Z", "+00:00"))
        except ValueError:
            pass

    duration = a.get("duration")
    if not end_dt and duration and start_dt:
        end_dt = start_dt + timedelta(seconds=int(duration))

    sport = a.get("sport") or {}
    league = a.get("league") or {}
    category = a.get("category") or {}
    subcategory = a.get("subcategory") or {}
    program = a.get("program") or {}
    image = a.get("image") or {}

    return {
        "title": name,
        "short_name": a.get("shortName") or name,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat() if end_dt else None,
        "start_timestamp": int(start_dt.timestamp()),
        "end_timestamp": int(end_dt.timestamp()) if end_dt else None,
        "sport": sport.get("name") or "",
        "sport_abbrev": sport.get("abbreviation") or "",
        "league": league.get("name") or "",
        "league_abbrev": league.get("abbreviation") or "",
        "category": category.get("name") or "",
        "subcategory": subcategory.get("name") or "",
        "is_studio": bool(program.get("isStudio")),
        "image_url": image.get("url") or "",
        "id": a.get("id") or "",
    }


async def fetch_espn_plus_schedule(
    day_iso: str,
    http_client: httpx.AsyncClient,
    tz: str = "America/New_York",
) -> list[dict]:
    variables = {"day": day_iso, "tz": tz}
    params = {
        "apiKey": ESPN_WATCH_API_KEY,
        "query": QUERY,
        "variables": json.dumps(variables),
    }
    url = f"{ESPN_WATCH_GRAPHQL_URL}?{urlencode(params)}"
    try:
        resp = await http_client.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"ESPN Watch API call failed for day={day_iso}: {e}")
        return []

    if "errors" in data:
        logger.warning(f"ESPN Watch API errors for day={day_iso}: {data['errors']}")
        return []

    arr = (((data or {}).get("data") or {}).get("airings") or [])
    parsed = [p for p in (_parse_airing(a) for a in arr) if p]
    logger.info(f"Downloaded ESPN+ schedule: {len(parsed)} airings (day={day_iso})")
    return parsed
