# Dispatcharr ESPN+ EPG Generator

Automatically discovers ESPN+ event streams from a Dispatcharr source playlist, matches them to ESPN event metadata, creates a high-quality XMLTV guide, and assigns channels to the **EPG** profile within Dispatcharr.

## Architecture

```
M3U Playlist → Parse → Filter ESPN+ → Match to ESPN Events → Generate XMLTV → Upload to Dispatcharr → Assign EPG Profile
```

Runs continuously, monitoring the playlist for changes, and only rebuilds when the playlist changes.

## Quick Start

1. **Configure** `config/config.yaml`:
   ```yaml
   playlist_url: "http://your-m3u-url/playlist.m3u"
   dispatcharr:
     base_url: "http://192.168.0.168:9191"
     username: "admin"
     password: "admin"
   ```

2. **Run with Docker**:
   ```bash
   docker-compose up -d
   ```

3. **Run once** (outside Docker):
   ```bash
   pip install -r requirements.txt
   python -m src.main --config config.yaml --once
   ```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `dispatcharr.base_url` | `http://192.168.0.168:9191` | Dispatcharr instance URL |
| `dispatcharr.username` | `admin` | Dispatcharr username |
| `dispatcharr.password` | `admin` | Dispatcharr password |
| `dispatcharr.api_key` | — | Alternative to username/password |
| `epg.source_name` | `ESPN+ EPG` | EPG source name in Dispatcharr |
| `epg.channel_id_prefix` | `ESPN+` | Prefix for XMLTV channel IDs |
| `espn.date` | `today` | Date for ESPN schedule (YYYYMMDD or "today") |
| `matching.min_similarity` | `0.90` | Minimum RapidFuzz similarity score |
| `matching.keyword` | `ESPN+` | Keyword to filter playlist channels |
| `poll_interval_minutes` | `120` | Minutes between playlist checks |

## Matching Algorithm

1. Filter playlist channels by `ESPN+` keyword
2. Extract start time from `tvg-id` (Unix timestamp)
3. Filter ESPN events by exact start time (±5 min)
4. Normalize titles (lowercase, remove punctuation, normalize `vs`/`@`/`at`)
5. Use RapidFuzz `token_sort_ratio` for fuzzy matching
6. Minimum 90% similarity threshold

## Project Structure

```
├── src/
│   ├── main.py          # Application entry point and main loop
│   ├── config.py        # Configuration loader
│   ├── playlist.py      # M3U parser and ESPN+ filter
│   ├── espn.py          # ESPN schedule scraper
│   ├── normalize.py     # Title normalization
│   ├── matcher.py       # Fuzzy matching with RapidFuzz
│   ├── xmltv_gen.py     # XMLTV document generator
│   ├── dispatcharr.py   # Dispatcharr REST API client
│   └── cache.py         # Playlist hash and data caching
├── tests/               # Unit tests
├── config/              # Configuration files
├── output/              # Generated XMLTV files
├── cache/               # Cached data
├── logs/                # Log files
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## API Endpoints Used

- `POST /api/accounts/token/` — Authentication
- `GET /api/channels/profiles/` — List channel profiles
- `GET /api/channels/channels/` — List/manage channels
- `POST /api/channels/channels/` — Create channels
- `PATCH /api/channels/channels/{id}/` — Update channels
- `PATCH /api/channels/profiles/{profile_id}/channels/{channel_id}/` — Profile membership
- `PATCH /api/channels/profiles/{profile_id}/channels/bulk-update/` — Bulk profile membership
- `GET/POST /api/epg/sources/` — Manage EPG sources
- `POST /api/epg/sources/upload/` — Upload XMLTV
- `POST /api/epg/import/` — Trigger EPG refresh
- `POST /api/channels/channels/batch-set-epg/` — Set EPG associations
