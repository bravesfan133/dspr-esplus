import asyncio
import json
import logging
import logging.handlers
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.cache import Cache, compute_playlist_hash
from src.config import Config
from src.dispatcharr import DispatcharrClient
from src.espn import fetch_espn_plus_schedule
from src.matcher import match_events
from src.playlist import streams_from_dispatcharr, filter_espn_plus, remove_no_event, filter_entries_by_day
from src.extract import extract_channel_number_index
from src.xmltv_gen import generate_xmltv

logger = logging.getLogger("espnplus")


def setup_logging(cfg: Config):
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, cfg.logging.level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    if cfg.logging.file:
        file_handler = logging.handlers.RotatingFileHandler(
            cfg.logging.file, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_espn_days(cfg: Config) -> list[str]:
    if cfg.espn.date.lower() == "today":
        eastern = ZoneInfo("US/Eastern")
        now_et = datetime.now(eastern)
        days = []
        for i in range(cfg.espn.look_ahead_days + 1):
            days.append((now_et + timedelta(days=i)).strftime("%Y-%m-%d"))
        return days
    return [cfg.espn.date]


async def run_once(cfg: Config, cache: Cache, dispatcharr: DispatcharrClient, dry_run: bool = False) -> bool:
    dispatcharr_streams = await dispatcharr.get_streams()

    playlist_hash = compute_playlist_hash(json.dumps(dispatcharr_streams, sort_keys=True, default=str))
    cached_hash = cache.load_hash()

    if cached_hash == playlist_hash:
        logger.info("Playlist unchanged — skipping")
        return False

    logger.info("Playlist changed")

    cache.save_hash(playlist_hash)

    all_entries = streams_from_dispatcharr(dispatcharr_streams)
    espn_entries = filter_espn_plus(all_entries, cfg.matching.keyword)
    espn_entries = remove_no_event(espn_entries)
    days = get_espn_days(cfg)
    espn_entries = filter_entries_by_day(espn_entries, days)
    logger.info(f"Found {len(espn_entries)} {cfg.matching.keyword} streams with events")

    espn_events = []
    async with asyncio.timeout(120):
        import httpx
        async with httpx.AsyncClient(timeout=30) as http:
            for day_iso in days:
                day_events = await fetch_espn_plus_schedule(day_iso, http)
                espn_events.extend(day_events)

    cache.save_espn_events(espn_events)

    matches = match_events(
        espn_entries,
        espn_events,
        min_similarity=cfg.matching.min_similarity,
    )

    matched_count = len(matches)
    logger.info(f"Matched {matched_count} events")

    if dry_run:
        logger.info("=== DRY RUN — no changes made to Dispatcharr ===")
        for entry, metadata in matches:
            start = metadata.get("start_time", "")[:19]
            end = metadata.get("end_time", "")[:19]
            sport = metadata.get("sport", "")
            league = metadata.get("league", "")
            subcat = metadata.get("subcategory", "")
            img = metadata.get("image_url", "")[:60] if metadata.get("image_url") else ""
            print(f"  MATCH: {entry.name}")
            print(f"         {start} -> {end}")
            print(f"         sport={sport} league={league} subcat={subcat}")
            if img:
                print(f"         img={img}")
            print()
        print(f"Total matches: {matched_count}")
        print(f"XMLTV saved to: {cfg.epg.xmltv_output}")
        return True

    if not matches:
        logger.warning("No matches found — skipping XMLTV and Dispatcharr update")
        return True

    xml_content = generate_xmltv(matches, prefix=cfg.epg.channel_id_prefix)
    logger.info("Generated XMLTV")

    output_path = cfg.epg.xmltv_output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    cache.save_last_epg(xml_content)

    await sync_to_dispatcharr(matches, cfg, dispatcharr, output_path)

    return True


async def sync_to_dispatcharr(
    matches: list[tuple],
    cfg: Config,
    dispatcharr: DispatcharrClient,
    xmltv_path: str,
):
    epg_profile = await dispatcharr.get_profile_by_name("EPG")
    if not epg_profile:
        logger.error("EPG profile not found in Dispatcharr!")
        return
    profile_id = epg_profile["id"]
    logger.info(f"Found EPG profile (id={profile_id})")

    channel_group_id = await dispatcharr.get_or_create_group(cfg.epg.epg_group_name)

    existing_channels = await dispatcharr.get_channels()
    existing_by_name = {ch["name"].lower(): ch for ch in existing_channels}

    from src.xmltv_gen import get_channel_id

    def sort_key(t):
        entry, _ = t
        n = extract_channel_number_index(entry.name)
        return (n is None, n if n is not None else 0)

    sorted_matches = sorted(matches, key=sort_key)

    xmltv_channel_id_to_ch_id = {}
    created_count = 0
    updated_count = 0
    profile_channel_ids = []

    for entry, metadata in sorted_matches:
        xmltv_id = get_channel_id(entry, prefix=cfg.epg.channel_id_prefix)
        n = extract_channel_number_index(entry.name)
        target_channel_number = cfg.epg.channel_number_start + (n - 1) if n is not None else None
        existing = existing_by_name.get(entry.name.lower())

        if existing:
            ch_id = existing["id"]
            await dispatcharr.update_channel(ch_id, entry, channel_group_id, tvg_id=xmltv_id)
            if target_channel_number is not None and existing.get("channel_number") is None:
                await dispatcharr.set_channel_number(ch_id, target_channel_number)
            updated_count += 1
        else:
            new_ch = await dispatcharr.create_channel(
                entry,
                group_id=channel_group_id,
                channel_number=target_channel_number,
                tvg_id=xmltv_id,
            )
            ch_id = new_ch["id"]
            created_count += 1

        xmltv_channel_id_to_ch_id[xmltv_id] = ch_id
        profile_channel_ids.append(ch_id)

    if created_count > 0 or updated_count > 0:
        logger.info(f"Created {created_count} new Dispatcharr channels")
        logger.info(f"Updated {updated_count} existing channels")

        if profile_channel_ids:
            await dispatcharr.bulk_add_channels_to_profile(profile_channel_ids, profile_id)
            logger.info("Assigned channels to EPG profile")

        with open(xmltv_path, "rb") as f:
            xml_content = f.read()

        epg_source = await dispatcharr.upload_xmltv(cfg.epg.source_name, "xmltv", xml_content.decode("utf-8"))
        epg_source_id = epg_source["id"]
        await dispatcharr.trigger_epg_refresh(epg_source_id)

        epg_rows_by_id = {}
        for attempt in range(5):
            await asyncio.sleep(2.0)
            rows = await dispatcharr.list_epg_data()
            epg_rows_by_id = {r.get("tvg_id"): r for r in rows if r.get("tvg_id")}
            matched_keys = set(xmltv_channel_id_to_ch_id.keys())
            available_keys = set(epg_rows_by_id.keys())
            if matched_keys <= available_keys:
                break

        associations = []
        for entry, metadata in matches:
            from src.xmltv_gen import get_channel_id
            xmltv_id = get_channel_id(entry, prefix=cfg.epg.channel_id_prefix)
            epg_row = epg_rows_by_id.get(xmltv_id)
            ch_id = xmltv_channel_id_to_ch_id.get(xmltv_id)
            if epg_row and ch_id:
                associations.append({"channel_id": ch_id, "epg_data_id": epg_row["id"]})

        if associations:
            await dispatcharr.batch_set_epg(associations)
            logger.info(f"Assigned EPG data to {len(associations)} channels")
            await dispatcharr.trigger_epg_refresh(epg_source_id)
            if await dispatcharr.wait_for_epg_refresh(epg_source_id, timeout=90):
                logger.info("EPG programme data imported")
            else:
                logger.warning("Timed out waiting for EPG programme import")
        else:
            logger.warning("No EPG associations could be built (rows not yet populated)")

        logger.info("Triggered Dispatcharr refresh")
        logger.info("Completed successfully")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Dispatcharr ESPN+ EPG Generator")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and match only — no Dispatcharr changes")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    cfg.ensure_dirs()
    setup_logging(cfg)

    cache = Cache(cfg.cache_dir)

    async def run():
        async with DispatcharrClient(
            base_url=cfg.dispatcharr.base_url,
            username=cfg.dispatcharr.username,
            password=cfg.dispatcharr.password,
            api_key=cfg.dispatcharr.api_key,
        ) as dispatcharr:
            await dispatcharr.authenticate()

            if args.once or args.dry_run:
                await run_once(cfg, cache, dispatcharr, dry_run=args.dry_run)
                return

            while True:
                try:
                    changed = await run_once(cfg, cache, dispatcharr)
                except Exception as e:
                    logger.error(f"Run failed: {e}", exc_info=True)
                    changed = False

                logger.info(f"Waiting {cfg.poll_interval_minutes} minutes for next check...")
                await asyncio.sleep(cfg.poll_interval_minutes * 60)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
