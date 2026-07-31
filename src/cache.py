import hashlib
import json
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.cache_dir / name

    def load_hash(self) -> Optional[str]:
        path = self._path("playlist.hash")
        if path.exists():
            with open(path) as f:
                return f.read().strip()
        return None

    def save_hash(self, hash_value: str):
        with open(self._path("playlist.hash"), "w") as f:
            f.write(hash_value)
        logger.debug("Saved playlist hash")

    def load_espn_events(self) -> Optional[list]:
        path = self._path("espn_events.json")
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def save_espn_events(self, events: list):
        with open(self._path("espn_events.json"), "w") as f:
            json.dump(events, f, indent=2, default=str)
        logger.debug("Saved ESPN events cache")

    def load_last_epg(self) -> Optional[str]:
        path = self._path("last_epg.xml")
        if path.exists():
            with open(path) as f:
                return f.read()
        return None

    def save_last_epg(self, xml_content: str):
        with open(self._path("last_epg.xml"), "w") as f:
            f.write(xml_content)
        logger.debug("Saved last EPG XML cache")


def compute_playlist_hash(playlist_data: str) -> str:
    return hashlib.sha256(playlist_data.encode("utf-8")).hexdigest()
