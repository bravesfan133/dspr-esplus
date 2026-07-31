import logging

from .engine import run_once, validate_settings
from .state import State

logger = logging.getLogger("espnplus")


class Plugin:
    name = "ESPN+ EPG"
    version = "1.0.0"
    description = (
        "Generates a custom ESPN+ EPG from your IPTV playlist by matching ESPN+ "
        "streams to ESPN's Watch schedule, then creates channels and assigns EPG "
        "data in Dispatcharr. Runs automatically after every M3U refresh."
    )
    author = "nick"

    def run(self, action_id, params, context):
        settings = ((context or {}).get("settings", {}) or {})
        try:
            if action_id == "run_now":
                return run_once(settings, dry_run=False, force=True)

            if action_id == "dry_run":
                return run_once(settings, dry_run=True, force=True)

            if action_id == "validate_settings":
                return validate_settings(settings)

            if action_id == "status":
                state = State()
                last_run = state.load_status()
                if last_run is None:
                    return {"status": "ok", "message": "No runs recorded yet"}
                return {"status": "ok", "last_run": last_run}

            if action_id == "auto_run":
                if not bool(settings.get("auto_refresh", True)):
                    return {
                        "status": "skipped",
                        "message": "Auto-refresh disabled in settings",
                    }
                return run_once(settings, dry_run=False)

            return {
                "status": "error",
                "message": f"Unknown action: {action_id}",
            }
        except Exception as e:
            logger.exception("Plugin action %s failed", action_id)
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}
