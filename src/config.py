import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class DispatcharrConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    api_key: str = ""


@dataclass
class EPGConfig:
    source_name: str = "ESPN+ EPG"
    xmltv_output: str = "output/espnplus_epg.xml"
    channel_id_prefix: str = "ESPN+"
    channel_number_start: float = 900.0
    epg_group_name: str = "ESPN+"


@dataclass
class ESPNConfig:
    date: str = "today"
    look_ahead_days: int = 1


@dataclass
class MatchingConfig:
    min_similarity: float = 0.85
    keyword: str = "ESPN+"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/espnplus.log"


@dataclass
class Config:
    dispatcharr: DispatcharrConfig = field(default_factory=DispatcharrConfig)
    epg: EPGConfig = field(default_factory=EPGConfig)
    espn: ESPNConfig = field(default_factory=ESPNConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    poll_interval_minutes: int = 120
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    cache_dir: str = "cache"

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        cfg = cls()

        da = data.get("dispatcharr", {})
        cfg.dispatcharr.base_url = da.get("base_url", cfg.dispatcharr.base_url)
        cfg.dispatcharr.username = da.get("username", "")
        cfg.dispatcharr.password = da.get("password", "")
        cfg.dispatcharr.api_key = da.get("api_key", "")

        ep = data.get("epg", {})
        cfg.epg.source_name = ep.get("source_name", cfg.epg.source_name)
        cfg.epg.xmltv_output = ep.get("xmltv_output", cfg.epg.xmltv_output)
        cfg.epg.channel_id_prefix = ep.get("channel_id_prefix", cfg.epg.channel_id_prefix)
        cfg.epg.channel_number_start = float(ep.get("channel_number_start", cfg.epg.channel_number_start))
        cfg.epg.epg_group_name = ep.get("epg_group_name", cfg.epg.epg_group_name)

        es = data.get("espn", {})
        cfg.espn.date = es.get("date", cfg.espn.date)
        cfg.espn.look_ahead_days = int(es.get("look_ahead_days", cfg.espn.look_ahead_days))

        mc = data.get("matching", {})
        cfg.matching.min_similarity = float(mc.get("min_similarity", cfg.matching.min_similarity))
        cfg.matching.keyword = mc.get("keyword", cfg.matching.keyword)

        cfg.poll_interval_minutes = int(data.get("poll_interval_minutes", cfg.poll_interval_minutes))

        lg = data.get("logging", {})
        cfg.logging.level = lg.get("level", cfg.logging.level)
        cfg.logging.file = lg.get("file", cfg.logging.file)

        cfg.cache_dir = data.get("cache_dir", cfg.cache_dir)

        return cfg

    def ensure_dirs(self):
        for d in [self.cache_dir, os.path.dirname(self.logging.file), os.path.dirname(self.epg.xmltv_output)]:
            os.makedirs(d, exist_ok=True)
