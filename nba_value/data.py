"""NBA acquisition and hash-verified, explicit offline snapshots."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .scoring import ADVANCED_COLUMNS, BASE_COLUMNS, DEFENSE_COLUMNS, select_columns

LOGGER = logging.getLogger(__name__)
TABLES = ("base", "advanced", "defense")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_snapshot(tables: dict[str, pd.DataFrame], directory: Path, season: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "season": season,
        "season_type": "Regular Season",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "NBA Stats via nba_api",
        "tables": {},
    }
    for name in TABLES:
        path = directory / f"{name}.csv"
        tables[name].to_csv(path, index=False, lineterminator="\n")
        manifest["tables"][name] = {
            "rows": len(tables[name]),
            "sha256": file_hash(path),
            "endpoint": "leaguedashptdefend" if name == "defense" else "leaguedashplayerstats",
            "parameters": {
                "Season": season,
                "SeasonType": "Regular Season",
                **(
                    {"DefenseCategory": "Overall", "PerMode": "Totals"}
                    if name == "defense"
                    else {"MeasureType": name.title(), "PerMode": "PerGame"}
                ),
            },
        }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_snapshot(directory: Path, season: str) -> tuple[dict[str, pd.DataFrame], dict]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["season"] != season or manifest["season_type"] != "Regular Season":
        raise ValueError("Snapshot season or season type does not match this run")
    tables = {}
    for name in TABLES:
        path = directory / f"{name}.csv"
        if file_hash(path) != manifest["tables"][name]["sha256"]:
            raise ValueError(f"Snapshot hash mismatch: {name}.csv")
        tables[name] = pd.read_csv(path)
        if len(tables[name]) != manifest["tables"][name]["rows"]:
            raise ValueError(f"Snapshot row-count mismatch: {name}")
    return tables, manifest


def fetch_table(name: str, season: str, *, timeout: int = 20, attempts: int = 3) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashptdefend
    from requests.exceptions import RequestException

    if name not in TABLES:
        raise ValueError(f"Unknown table: {name}")
    for attempt in range(attempts):
        try:
            if name == "defense":
                endpoint = leaguedashptdefend.LeagueDashPtDefend(
                    season=season,
                    season_type_all_star="Regular Season",
                    defense_category="Overall",
                    timeout=timeout,
                )
                df = endpoint.get_data_frames()[0].rename(
                    columns={"CLOSE_DEF_PERSON_ID": "PLAYER_ID"}
                )
                return select_columns(df, DEFENSE_COLUMNS)
            endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season,
                season_type_all_star="Regular Season",
                measure_type_detailed_defense=name.title(),
                per_mode_detailed="PerGame",
                timeout=timeout,
            )
            return select_columns(
                endpoint.get_data_frames()[0], BASE_COLUMNS if name == "base" else ADVANCED_COLUMNS
            )
        except (RequestException, ValueError):
            if attempt + 1 == attempts:
                raise
            time.sleep(2**attempt)
    raise ValueError("attempts must be positive")


def fetch_season(season: str) -> dict[str, pd.DataFrame]:
    tables = {}
    for name in TABLES:
        LOGGER.info("Fetching %s for %s", name, season)
        try:
            tables[name] = fetch_table(name, season)
        except Exception:
            if name != "defense":
                raise
            LOGGER.warning("Defense unavailable; using flagged neutral values", exc_info=True)
            tables[name] = pd.DataFrame(columns=DEFENSE_COLUMNS)
        time.sleep(2)
    if tables["base"].empty or tables["advanced"].empty:
        raise ValueError("NBA returned empty required data")
    return tables
