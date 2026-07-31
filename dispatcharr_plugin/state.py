import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def compute_playlist_hash(playlist_data: str) -> str:
    return hashlib.sha256(playlist_data.encode("utf-8")).hexdigest()


class State:
    """Persists small run state inside the plugin's own directory."""

    def __init__(self, base_dir: Optional[str] = None):
        base = base_dir or os.environ.get("DISPATCHARR_PLUGINS_DIR", "/data/plugins")
        try:
            self.state_dir = Path(base) / ".state" / "dspr_esplus"
            self.state_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.state_dir = Path(tempfile.gettempdir()) / "dspr_esplus_state"
            self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.state_dir / name

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

    def save_status(self, data: dict):
        with open(self._path("last_run.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def load_status(self) -> Optional[dict]:
        path = self._path("last_run.json")
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return None
        return None
