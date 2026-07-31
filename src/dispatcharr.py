import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from src.playlist import PlaylistEntry

logger = logging.getLogger(__name__)

EPG_UPLOAD_DIR = "/data/uploads/epgs"


@dataclass
class DispatcharrChannel:
    id: int
    uuid: str
    name: str
    stream_url: str
    tvg_id: Optional[str] = None
    epg_data_id: Optional[int] = None
    channel_group_id: Optional[int] = None
    channel_number: Optional[float] = None


class DispatcharrClient:
    def __init__(self, base_url: str, username: str = "", password: str = "", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.api_key = api_key
        self._token: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=30.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._http.aclose()

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    async def authenticate(self):
        if self._token:
            return
        if self.api_key:
            return
        if not self.username or not self.password:
            raise ValueError("No credentials configured")

        try:
            resp = await self._http.post(
                f"{self.base_url}/api/accounts/token/",
                json={"username": self.username, "password": self.password},
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("access")
            logger.info("Authenticated with Dispatcharr")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

    async def get_profiles(self) -> list[dict]:
        resp = await self._http.get(
            f"{self.base_url}/api/channels/profiles/",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_profile_by_name(self, name: str) -> Optional[dict]:
        profiles = await self.get_profiles()
        for p in profiles:
            if p.get("name") == name:
                return p
        return None

    async def get_channels(self, params: Optional[dict] = None) -> list[dict]:
        all_channels = []
        url = f"{self.base_url}/api/channels/channels/"
        query_params = params or {}
        query_params["page_size"] = 5000

        while url:
            resp = await self._http.get(url, headers=self._headers(), params=query_params)
            resp.raise_for_status()
            data = resp.json()
            all_channels.extend(data.get("results", []))
            url = data.get("next")
            query_params = {}

        return all_channels

    async def get_channel_by_name(self, name: str) -> Optional[dict]:
        channels = await self.get_channels({"search": name})
        for ch in channels:
            if ch.get("name", "").lower() == name.lower():
                return ch
        return None

    async def create_channel(
        self,
        entry: PlaylistEntry,
        group_id: Optional[int] = None,
        channel_number: Optional[float] = None,
        tvg_id: Optional[str] = None,
    ) -> dict:
        payload = {
            "name": entry.name,
            "tvg_id": tvg_id or entry.tvg_id or "",
            "streams": [entry.stream_id] if entry.stream_id else [],
        }
        if group_id is not None:
            payload["channel_group_id"] = group_id
        if channel_number is not None:
            payload["channel_number"] = float(channel_number)
        elif entry.tvg_chno:
            try:
                payload["channel_number"] = float(entry.tvg_chno)
            except (ValueError, TypeError):
                pass

        resp = await self._http.post(
            f"{self.base_url}/api/channels/channels/",
            headers=self._headers(),
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error(f"Failed to create channel: {resp.status_code} {resp.text}")
            raise
        channel = resp.json()
        logger.info(f"Created channel '{entry.name}' (id={channel.get('id')})")
        return channel

    async def update_channel(
        self,
        channel_id: int,
        entry: PlaylistEntry,
        group_id: Optional[int] = None,
        tvg_id: Optional[str] = None,
    ):
        payload = {
            "name": entry.name,
            "tvg_id": tvg_id or entry.tvg_id or "",
        }
        if entry.stream_id:
            payload["streams"] = [entry.stream_id]
        if group_id is not None:
            payload["channel_group_id"] = group_id

        resp = await self._http.patch(
            f"{self.base_url}/api/channels/channels/{channel_id}/",
            headers=self._headers(),
            json=payload,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning(f"Failed to update channel {channel_id}: {resp.status_code}")
            return None
        logger.debug(f"Updated channel {channel_id} '{entry.name}'")
        return resp.json()

    async def get_or_create_group(self, group_name: str) -> int:
        resp = await self._http.get(
            f"{self.base_url}/api/channels/groups/",
            headers=self._headers(),
        )
        resp.raise_for_status()
        groups = resp.json()
        for g in groups:
            if g.get("name", "").lower() == group_name.lower():
                return g["id"]

        resp = await self._http.post(
            f"{self.base_url}/api/channels/groups/",
            headers=self._headers(),
            json={"name": group_name},
        )
        resp.raise_for_status()
        new_group = resp.json()
        logger.info(f"Created channel group '{group_name}' (id={new_group['id']})")
        return new_group["id"]

    async def add_channel_to_profile(self, channel_id: int, profile_id: int, enabled: bool = True):
        resp = await self._http.patch(
            f"{self.base_url}/api/channels/profiles/{profile_id}/channels/{channel_id}/",
            headers=self._headers(),
            json={"enabled": enabled},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning(f"Failed to add channel {channel_id} to profile {profile_id}: {resp.status_code}")
            return None
        return resp.json()

    async def bulk_add_channels_to_profile(self, channel_ids: list[int], profile_id: int, enabled: bool = True):
        if not channel_ids:
            return
        payload = {
            "channels": [
                {"channel_id": cid, "enabled": enabled}
                for cid in channel_ids
            ]
        }
        resp = await self._http.patch(
            f"{self.base_url}/api/channels/profiles/{profile_id}/channels/bulk-update/",
            headers=self._headers(),
            json=payload,
        )
        try:
            resp.raise_for_status()
            logger.info(f"Bulk-added {len(channel_ids)} channels to profile {profile_id}")
        except httpx.HTTPStatusError:
            logger.warning(f"Bulk profile update failed: {resp.status_code}")
            for cid in channel_ids:
                await self.add_channel_to_profile(cid, profile_id, enabled)

    async def get_epg_sources(self) -> list[dict]:
        resp = await self._http.get(
            f"{self.base_url}/api/epg/sources/",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def upload_xmltv(
        self,
        name: str,
        source_type: str = "xmltv",
        xml_content: str = "",
        filename: str = "espnplus_epg.xml",
    ) -> dict:
        try:
            auth_headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
            if self.api_key and not self._token:
                auth_headers["Authorization"] = f"ApiKey {self.api_key}"
            resp = await self._http.post(
                f"{self.base_url}/api/epg/sources/upload/",
                headers=auth_headers,
                data={
                    "name": name,
                    "source_type": source_type,
                    "is_active": "true",
                    "refresh_interval": "1440",
                    "priority": "1",
                },
                files={"file": (filename, xml_content.encode("utf-8"), "application/xml")},
            )

            if resp.status_code == 201:
                source = resp.json()
                logger.info(f"Uploaded XMLTV and created EPG source '{name}' (id={source['id']})")
                return source

            if resp.status_code == 400 and "already exists" in (resp.text or ""):
                logger.info(f"EPG source '{name}' already exists — overwriting its uploaded file")
                return await self._attach_uploaded_file_to_existing(name, filename)

            resp.raise_for_status()
            source = resp.json()
            logger.info(f"Uploaded XMLTV to EPG source (id={source.get('id')})")
            return source
        except httpx.HTTPStatusError as e:
            body_text = e.response.text[:300] if e.response is not None else ""
            logger.warning(f"XMLTV upload failed: {e.response.status_code} {body_text}")
            raise

    async def _attach_uploaded_file_to_existing(self, name: str, filename: str) -> dict:
        file_path = f"{EPG_UPLOAD_DIR}/{filename}"
        sources = await self.get_epg_sources()
        for s in sources:
            if s.get("name", "").lower() == name.lower():
                if s.get("file_path") != file_path:
                    await self._http.patch(
                        f"{self.base_url}/api/epg/sources/{s['id']}/",
                        headers=self._headers(),
                        json={"file_path": file_path},
                    )
                    logger.info(f"Pointed existing EPG source '{name}' (id={s['id']}) at uploaded file")
                return s
        logger.warning(f"Could not find existing EPG source '{name}' after duplicate upload")
        raise RuntimeError(f"EPG source '{name}' not found")

    async def set_channel_number(self, channel_id: int, channel_number: float) -> None:
        resp = await self._http.patch(
            f"{self.base_url}/api/channels/channels/{channel_id}/",
            headers=self._headers(),
            json={"channel_number": float(channel_number)},
        )
        resp.raise_for_status()

    async def list_epg_data(self) -> list[dict]:
        resp = await self._http.get(
            f"{self.base_url}/api/epg/epgdata/",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def trigger_epg_refresh(self, source_id: int):
        resp = await self._http.post(
            f"{self.base_url}/api/epg/import/",
            headers=self._headers(),
            json={"id": source_id},
        )
        try:
            resp.raise_for_status()
            logger.info("Triggered EPG refresh")
        except httpx.HTTPStatusError:
            logger.warning(f"EPG refresh trigger returned {resp.status_code}")

    async def wait_for_epg_refresh(self, source_id: int, timeout: float = 90.0, interval: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sources = await self.get_epg_sources()
            for s in sources:
                if s.get("id") == source_id:
                    status = s.get("status") or ""
                    message = s.get("last_message") or ""
                    if status == "success" and "programs for" in message:
                        logger.info(f"EPG refresh complete: {message}")
                        return True
                    if status in ("error", "disabled"):
                        logger.warning(f"EPG refresh failed for source {source_id}: {message}")
                        return False
                    break
            await asyncio.sleep(interval)
        logger.warning(f"Timed out waiting for EPG refresh of source {source_id}")
        return False

    async def batch_set_epg(self, associations: list[dict]):
        if not associations:
            return
        resp = await self._http.post(
            f"{self.base_url}/api/channels/channels/batch-set-epg/",
            headers=self._headers(),
            json={"associations": associations},
        )
        try:
            resp.raise_for_status()
            logger.info(f"Set EPG for {len(associations)} channels")
        except httpx.HTTPStatusError:
            logger.warning(f"Batch set EPG failed: {resp.status_code}")

    async def get_streams(self, params: Optional[dict] = None) -> list[dict]:
        all_streams = []
        url = f"{self.base_url}/api/channels/streams/"
        query_params = params or {}
        query_params["page_size"] = 5000

        while url:
            resp = await self._http.get(url, headers=self._headers(), params=query_params)
            resp.raise_for_status()
            data = resp.json()
            all_streams.extend(data.get("results", []))
            url = data.get("next")
            query_params = {}

        return all_streams

    async def trigger_epg_match(self, channel_ids: Optional[list[int]] = None):
        payload = {}
        if channel_ids:
            payload["channel_ids"] = channel_ids
        resp = await self._http.post(
            f"{self.base_url}/api/channels/channels/match-epg/",
            headers=self._headers(),
            json=payload,
        )
        try:
            resp.raise_for_status()
            logger.info("Triggered EPG matching task")
        except httpx.HTTPStatusError:
            logger.warning(f"EPG match trigger returned {resp.status_code}")
