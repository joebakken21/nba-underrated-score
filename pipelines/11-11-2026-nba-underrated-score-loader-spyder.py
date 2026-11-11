# -*- coding: utf-8 -*-
"""
NBA Underrated Score v2.1 loader (Spyder edition)
=================================================

What it does
------------
1. Pulls one season of player data from the NBA Stats API (nba_api).
2. Scores every player (5+ minutes per game) with Underrated Score v2.1.
3. Saves a CSV of the scores next to this file.
4. Refreshes the public dashboard's data file in docs/data/ (see PAGES_EXPORT).
5. Replaces that season's rows in BigQuery:
       <PROJECT>.nba_underrated_score.player_scores   (PROJECT is set in SETTINGS)
   Rows for other seasons are kept as they are. No other table or dataset
   is touched. Works on BigQuery's free tier (no billing needed).

How to run it in Spyder
-----------------------
One-time setup (in Anaconda Prompt, not Spyder's console, which rejects %pip):
    python -m pip install nba_api pandas numpy google-cloud-bigquery pyarrow db-dtypes
Run it with the python.exe of the Anaconda install that Spyder uses, then
restart Spyder's kernel (Consoles > Restart kernel).
Set PROJECT in the SETTINGS cell to your own Google Cloud project ID.
Then sign in to Google Cloud once (Anaconda Prompt or a terminal):
    gcloud auth application-default login
If "gcloud" isn't found, install the Google Cloud CLI first.

Each run:
    1. Open this file in Spyder.
    2. Check the SETTINGS cell (season, dry run, optional files).
    3. Press F5 (Run file). Or run the cells top to bottom with Shift+Enter.
    4. Read the console. Every stage prints what it did, and every known
       problem prints a plain-words explanation and what to do about it.

After a run, these are in the Variable Explorer:
    frames     the raw nba_api tables (dict of DataFrames)
    scores     the scored players, one row per player

Updating the public dashboard (GitHub Pages):
    The page in docs/index.html reads docs/data/player_scores_<SEASON>.csv.
    Each run rewrites that file. Commit and push it, and the page shows the
    new numbers a minute or two later. Set PAGES_EXPORT to False to skip it.

Re-running is cheap: the raw pull is cached in the "cache" folder next to this
file, so a second run the same day skips the slow download. Set USE_CACHE to
False to force a fresh pull.

The formula (v2.1)
------------------
    Underrated Score = (PV x Penalty) / max(RI, 5)        PV and RI on 0-100

    PV  Production Value = 0.35 Efficiency + 0.30 Role Difficulty + 0.35 Versatility
        Efficiency      = 0.34 TS + 0.23 Playmaking + 0.43 On/Off Net Rating
        Role Difficulty = 0.40 DefVersatility + 0.33 Workload + 0.27 LineupStrength (carry tax)
        Versatility     = 0.34 PositionalFlex + 0.43 TwoWayImpact + 0.23 SkillDiversity

    RI  Investment Index = 0.40 Financial + 0.35 Usage + 0.25 Recognition
        Financial   = 0.65 salary as % of max-eligible + 0.35 dollars per production
        Usage       = 0.40 USG% + 0.33 MPG + 0.27 touches
        Recognition = 0.40 All-Star votes + 0.60 awards (linear 5-year decay)

    Penalty: NetRtg < -10 or TS% < .45 -> 0.30
             NetRtg < -5               -> 0.60
             NetRtg < 0 and TS% < .52  -> 0.80
             otherwise                 -> 1.00
    Gates:   GP >= 30 (scaled to games played so far), MPG >= 15, PV >= 50
    Tiers:   2.0+ Seriously Underrated | 1.5-2.0 Quietly Valuable |
             1.0-1.5 Fairly Rated      | under 1.0 Properly Rated

Approximations (also written to the "approximations" column of every row)
------------------------------------------------------------------------
- DefVersatility: opponent FG% vs expected on contested shots (nba_api has no
  matchup-by-position data).
- TwoWayImpact: on-court offensive and defensive rating vs league average,
  standing in for OBPM + DBPM.
- PositionalFlex: roster position listing (G, G-F, F-C ...), standing in for
  minutes by position.
- LineupStrength: team net rating with the player off the floor.
- Salary and All-Star votes: estimated unless you give the optional files.
- Every component is scaled 0-100 by percentile among scored players.
"""

# %% SETTINGS: the only cell you normally change
# ---------------------------------------------------------------------------

SEASON = "2026-27"  # NBA season to score, written as "YYYY-YY"
DRY_RUN = False  # True = score and save the CSV, skip BigQuery

# Optional files. Leave as None to use the built-in estimates.
#   SALARY_FILE columns: PLAYER_NAME, SALARY            (MAX_ELIGIBLE optional)
#   VOTES_FILE  columns: PLAYER_NAME, VOTES
SALARY_FILE = None  # e.g. r"C:\path\to\salaries_2026-27.csv"
VOTES_FILE = None  # e.g. r"C:\path\to\allstar_votes.csv"

USE_CACHE = True  # reuse today's raw pull if it exists

# Public dashboard data file. Written to docs/data/ in this repository each run.
PAGES_EXPORT = True  # False = don't touch the dashboard's CSV
MAX_SALARY = 0.35 * 154_647_000  # one league-wide max tier, used without MAX_ELIGIBLE

# BigQuery destination. Only rows for SEASON in this table are replaced.
PROJECT = "your-gcp-project-id"  # replace with your Google Cloud project ID
DATASET = "nba_underrated_score"
TABLE_NAME = "player_scores"


# %% IMPORTS AND PACKAGE CHECK
# ---------------------------------------------------------------------------
# Standard-library imports never fail. The third-party ones are checked one by
# one so a missing package gives you the exact install command, not a traceback.

import datetime as dt
import importlib
import os
import time
import traceback


class LoaderError(Exception):
    """A known problem, explained in plain words. The run stops cleanly."""


def require(module_name, pip_name=None):
    """Import a package, or stop with the install command if it's missing."""
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise LoaderError(
            f"The package '{pip_name or module_name}' isn't installed.\n"
            f"Fix: open Anaconda Prompt and run\n"
            f"    python -m pip install {pip_name or module_name}\n"
            f"using the Anaconda install that Spyder runs (Spyder's console rejects %pip).\n"
            f"Then restart the kernel (Consoles > Restart kernel) and run again."
        ) from None


pd = require("pandas")
np = require("numpy")

# Folder this file lives in. Falls back to the current folder when a cell is
# run on its own (Spyder doesn't set __file__ then).
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.getcwd()

TABLE = f"{PROJECT}.{DATASET}.{TABLE_NAME}"
FORMULA_VERSION = "v2.1"
MIN_MPG_SCORED = 5.0  # players under this aren't scored at all
FULL_SEASON_GP_GATE = 30
FULL_SEASON_GAMES = 82
NBA_TIMEOUT = 60  # seconds per stats.nba.com request
NBA_RETRIES = 3  # attempts per request before giving up
NBA_PAUSE = 0.7  # seconds between requests (stats.nba.com rate-limits bursts)

APPROX_BASE = [
    "DefVersatility uses opponent FG% vs expected on contested shots (no matchup-position data in nba_api)",
    "TwoWayImpact uses on-court offensive and defensive rating vs league average in place of OBPM/DBPM",
    "PositionalFlex uses the roster position listing (G, G-F, F-C, ...) in place of minutes by position",
    "LineupStrength (carry tax) uses the team's net rating with the player off the floor",
    "Components are scaled 0-100 by percentile among scored players",
]


def log(msg):
    """Timestamped console line, so you can see where a slow run is."""
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# %% STAGE 1: FETCH FROM STATS.NBA.COM
# ---------------------------------------------------------------------------
# Eight kinds of tables, plus one on/off call per team and one awards call per
# player. A full pull takes roughly 6 to 10 minutes because of the pauses.


def nba_call(label, make_request):
    """Run one nba_api request with retries and plain-words errors.

    make_request is a no-argument function that returns the endpoint's
    DataFrames. Timeouts and connection drops are retried with a growing wait;
    after NBA_RETRIES failures the run stops with an explanation.
    """
    last = None
    for attempt in range(1, NBA_RETRIES + 1):
        try:
            frames = make_request()
            time.sleep(NBA_PAUSE)
            return frames
        except Exception as exc:  # nba_api raises requests, JSON and key errors
            last = exc
            wait = 5 * attempt
            log(
                f"  {label}: attempt {attempt} of {NBA_RETRIES} failed ({type(exc).__name__}). "
                f"{'Retrying in ' + str(wait) + 's.' if attempt < NBA_RETRIES else ''}"
            )
            if attempt < NBA_RETRIES:
                time.sleep(wait)
    name = type(last).__name__
    if "Timeout" in name or "timed out" in str(last).lower():
        why = "stats.nba.com stopped answering (timeout)."
    elif "JSON" in name or "Expecting value" in str(last):
        why = "stats.nba.com sent back a page instead of data, which usually means it's blocking the request."
    elif "Connection" in name or "Proxy" in name or "SSL" in name:
        why = "your computer couldn't connect to stats.nba.com."
    else:
        why = f"an unexpected error: {name}: {last}"
    raise LoaderError(
        f"Couldn't get '{label}' from the NBA Stats API: {why}\n"
        "Fixes to try: wait a few minutes and run again; turn off a VPN; avoid work or school "
        "networks, which stats.nba.com often blocks; check nba_api is up to date "
        "(in Anaconda Prompt: python -m pip install -U nba_api)."
    )


def check_frame(df, label, needed):
    """Stop if an nba_api table came back empty or without the columns we use."""
    if df is None or len(df) == 0:
        raise LoaderError(
            f"'{label}' came back empty for {SEASON}. Either no games have been played yet, "
            f"or the season is typed wrong in SETTINGS (it should look like 2026-27)."
        )
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise LoaderError(
            f"'{label}' is missing columns {missing}. The NBA Stats API may have changed. "
            f"Update nba_api (in Anaconda Prompt: python -m pip install -U nba_api) and run again."
        )
    return df


def fetch_frames(season):
    """Every nba_api table the scorer needs, as a dict of DataFrames."""
    ep = require("nba_api.stats.endpoints", "nba_api")
    common = dict(season=season, season_type_all_star="Regular Season", timeout=NBA_TIMEOUT)
    frames = {}

    log("Pulling per-game box score stats ...")
    frames["base"] = check_frame(
        nba_call(
            "per-game stats",
            lambda: ep.leaguedashplayerstats.LeagueDashPlayerStats(
                per_mode_detailed="PerGame", measure_type_detailed_defense="Base", **common
            ).get_data_frames(),
        )[0],
        "per-game stats",
        [
            "PLAYER_ID",
            "PLAYER_NAME",
            "TEAM_ABBREVIATION",
            "GP",
            "MIN",
            "PTS",
            "REB",
            "AST",
            "STL",
            "BLK",
        ],
    )

    log("Pulling advanced stats ...")
    frames["adv"] = check_frame(
        nba_call(
            "advanced stats",
            lambda: ep.leaguedashplayerstats.LeagueDashPlayerStats(
                per_mode_detailed="PerGame", measure_type_detailed_defense="Advanced", **common
            ).get_data_frames(),
        )[0],
        "advanced stats",
        [
            "PLAYER_ID",
            "TS_PCT",
            "USG_PCT",
            "NET_RATING",
            "AST_PCT",
            "AST_TO",
            "OFF_RATING",
            "DEF_RATING",
        ],
    )

    log("Pulling defense tracking ...")
    frames["defend"] = check_frame(
        nba_call(
            "defense tracking",
            lambda: ep.leaguedashptdefend.LeagueDashPtDefend(
                defense_category="Overall",
                per_mode_simple="PerGame",
                season=season,
                timeout=NBA_TIMEOUT,
            ).get_data_frames(),
        )[0],
        "defense tracking",
        ["CLOSE_DEF_PERSON_ID", "PCT_PLUSMINUS", "D_FGA"],
    )

    log("Pulling touches ...")
    frames["touches"] = check_frame(
        nba_call(
            "touches",
            lambda: ep.leaguedashptstats.LeagueDashPtStats(
                player_or_team="Player",
                pt_measure_type="Possessions",
                per_mode_simple="PerGame",
                season=season,
                timeout=NBA_TIMEOUT,
            ).get_data_frames(),
        )[0],
        "touches",
        ["PLAYER_ID", "TOUCHES"],
    )

    log("Pulling team stats ...")
    frames["teams"] = check_frame(
        nba_call(
            "team stats",
            lambda: ep.leaguedashteamstats.LeagueDashTeamStats(
                measure_type_detailed_defense="Advanced", **common
            ).get_data_frames(),
        )[0],
        "team stats",
        ["TEAM_ID", "GP"],
    )

    log("Pulling roster positions ...")
    frames["index"] = check_frame(
        nba_call(
            "player index",
            lambda: ep.playerindex.PlayerIndex(
                season=season, timeout=NBA_TIMEOUT
            ).get_data_frames(),
        )[0],
        "player index",
        ["PERSON_ID", "POSITION"],
    )

    frames["onoff"] = fetch_onoff(ep, frames["teams"]["TEAM_ID"].tolist(), season)
    frames["awards"] = fetch_awards(ep, frames["base"])
    return frames


def fetch_onoff(ep, team_ids, season):
    """On-court and off-court net rating for every player, one call per team.

    A team that fails after retries is skipped with a warning; its players get
    a middle-of-the-pack (50) on/off score instead of stopping the whole run.
    """
    log(f"Pulling on/off splits for {len(team_ids)} teams ...")
    parts, skipped = [], []
    for team_id in team_ids:
        try:
            dfs = nba_call(
                f"on/off team {team_id}",
                lambda: ep.teamplayeronoffsummary.TeamPlayerOnOffSummary(
                    team_id=team_id,
                    season=season,
                    measure_type_detailed_defense="Advanced",
                    timeout=NBA_TIMEOUT,
                ).get_data_frames(),
            )
            # Pick the on-court and off-court tables by their COURT_STATUS column,
            # not by position, so a reordering in the API can't swap them.
            by_status = {
                str(f["COURT_STATUS"].iloc[0]).lower(): f
                for f in dfs
                if "COURT_STATUS" in f.columns and len(f)
            }
            on = by_status["on"][["VS_PLAYER_ID", "NET_RATING"]].rename(
                columns={"NET_RATING": "ON_NET"}
            )
            off = by_status["off"][["VS_PLAYER_ID", "NET_RATING"]].rename(
                columns={"NET_RATING": "OFF_NET"}
            )
            parts.append(on.merge(off, on="VS_PLAYER_ID", how="outer"))
        except (LoaderError, KeyError) as exc:
            skipped.append(team_id)
            log(f"  Skipping team {team_id}: {str(exc).splitlines()[0]}")
    if skipped:
        log(
            f"  On/off skipped for {len(skipped)} team(s); those players get a neutral on/off score."
        )
    if not parts:
        return pd.DataFrame(columns=["PLAYER_ID", "ON_NET", "OFF_NET"])
    return pd.concat(parts, ignore_index=True).rename(columns={"VS_PLAYER_ID": "PLAYER_ID"})


def fetch_awards(ep, base):
    """Career award rows for every scored player (one call per player).

    This is the slow part. A player whose call fails is skipped with a note;
    he simply gets no award credit.
    """
    ids = base.loc[base["MIN"] >= MIN_MPG_SCORED, "PLAYER_ID"].tolist()
    log(f"Pulling awards for {len(ids)} players (the slow part) ...")
    parts, skipped = [], 0
    for i, pid in enumerate(ids, 1):
        try:
            df = nba_call(
                f"awards {pid}",
                lambda: ep.playerawards.PlayerAwards(
                    player_id=pid, timeout=NBA_TIMEOUT
                ).get_data_frames(),
            )[0]
            if len(df):
                parts.append(df[["PERSON_ID", "DESCRIPTION", "SEASON"]])
        except (LoaderError, KeyError):
            skipped += 1
        if i % 50 == 0:
            log(f"  awards {i}/{len(ids)}")
    if skipped:
        log(f"  Awards skipped for {skipped} player(s); they get no award credit.")
    if not parts:
        return pd.DataFrame(columns=["PLAYER_ID", "DESCRIPTION", "SEASON"])
    return pd.concat(parts, ignore_index=True).rename(columns={"PERSON_ID": "PLAYER_ID"})


def cache_dir(season):
    return os.path.join(HERE, "cache", f"{season}_{dt.date.today():%Y-%m-%d}")


def save_cache(frames, season):
    """Save the raw pull so a re-run today skips the download."""
    folder = cache_dir(season)
    try:
        os.makedirs(folder, exist_ok=True)
        for name, df in frames.items():
            df.to_csv(os.path.join(folder, f"{name}.csv"), index=False)
        log(f"Raw pull cached in {folder}")
    except OSError as exc:
        log(f"  Couldn't write the cache ({exc}). The run continues without it.")


def load_cache(season):
    """Today's cached pull, or None if there isn't a complete one."""
    folder = cache_dir(season)
    names = ["base", "adv", "defend", "touches", "teams", "index", "onoff", "awards"]
    paths = {n: os.path.join(folder, f"{n}.csv") for n in names}
    if not all(os.path.exists(p) for p in paths.values()):
        return None
    log(f"Using today's cached pull from {folder}")
    return {n: pd.read_csv(p) for n, p in paths.items()}


# %% STAGE 2: SCORE (UNDERRATED SCORE v2.1)
# ---------------------------------------------------------------------------


def pct(values, higher_is_better=True):
    """Scale a column to 0-100 by percentile. Missing values land at 50."""
    s = pd.to_numeric(values, errors="coerce")
    return (s.rank(pct=True, ascending=higher_is_better) * 100).fillna(50.0)


def award_points(awards, season):
    """Weighted award credit with a linear 5-season decay.

    Last completed season counts 1.0, then 0.8, 0.6, 0.4, 0.2; older awards
    and the current season count 0. All-Star selections are also totalled
    separately, as the stand-in for All-Star votes.
    """
    weights = {
        "NBA Most Valuable Player": 10,
        "NBA Finals Most Valuable Player": 6,
        "All-NBA": 6,
        "NBA Defensive Player of the Year": 6,
        "All-Defensive Team": 3,
        "NBA All-Star": 3,
        "NBA Sixth Man of the Year": 3,
        "NBA Most Improved Player": 3,
        "NBA Rookie of the Year": 3,
        "NBA Clutch Player of the Year": 2,
        "All-Rookie Team": 1,
    }
    current = int(season[:4])
    rows = []
    for _, a in awards.iterrows():
        try:
            year = int(str(a["SEASON"])[:4])
        except ValueError:
            continue  # award rows without a season can't be dated
        age = current - year
        if not 1 <= age <= 5:
            continue
        decay = (6 - age) / 5
        desc = str(a["DESCRIPTION"])
        weight = next((w for k, w in weights.items() if desc.startswith(k)), 0)
        rows.append(
            {
                "PLAYER_ID": a["PLAYER_ID"],
                "award_pts": weight * decay,
                "allstar_pts": decay if desc.startswith("NBA All-Star") else 0.0,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["PLAYER_ID", "award_pts", "allstar_pts"])
    return pd.DataFrame(rows).groupby("PLAYER_ID", as_index=False).sum()


def penalty(net_rating, ts_pct):
    """Performance penalty multiplier from the v2.1 spec."""
    if net_rating < -10 or ts_pct < 0.45:
        return 0.30
    if net_rating < -5:
        return 0.60
    if net_rating < 0 and ts_pct < 0.52:
        return 0.80
    return 1.00


def tier(score):
    """Rating label from the v2.1 tiers."""
    if score >= 2.0:
        return "Seriously Underrated"
    if score >= 1.5:
        return "Quietly Valuable"
    if score >= 1.0:
        return "Fairly Rated"
    return "Properly Rated"


def estimate_salary(df):
    """Fallback salary when no file is given: $1.5M to $35M by minutes and scoring."""
    load = (df["MIN"] / 36).clip(0, 1) * 0.6 + (df["PTS"] / 28).clip(0, 1) * 0.4
    return (1_500_000 + load * 33_500_000).round(-4).astype("int64")


def skill_diversity(df):
    """How evenly a player spreads production across PTS, REB, AST, STL, BLK (0-1).

    Each stat is first divided by the league average so 1 block counts about
    as much as 9 points. Then normalised entropy: 1.0 = perfectly balanced.
    """
    cols = ["PTS", "REB", "AST", "STL", "BLK"]
    scaled = pd.DataFrame({c: df[c] / max(df[c].mean(), 1e-9) for c in cols})
    share = scaled.div(scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    entropy = -(share * np.log(share.where(share > 0, 1))).sum(axis=1)
    return entropy / np.log(len(cols))


def position_slots(positions):
    """Number of listed positions: G = 1, G-F = 2, blank = 0."""
    p = positions.fillna("").astype(str)
    return p.str.count("-") + (p.str.len() > 0).astype(int)


def read_optional_csv(path, needed, label):
    """Read an optional input file, or stop with a clear message if it's unusable."""
    if path is None:
        return None
    if not os.path.exists(path):
        raise LoaderError(
            f"The {label} file wasn't found at:\n  {path}\n"
            f"Fix the path in SETTINGS, or set it to None to use the estimate."
        )
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise LoaderError(f"The {label} file couldn't be read as a CSV ({exc}).") from None
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise LoaderError(
            f"The {label} file is missing column(s) {missing}. "
            f"It needs: {', '.join(needed)} (it has: {', '.join(map(str, df.columns))})."
        )
    if df["PLAYER_NAME"].duplicated().any():
        dupes = df.loc[df["PLAYER_NAME"].duplicated(), "PLAYER_NAME"].head(3).tolist()
        raise LoaderError(
            f"The {label} file lists some players twice, e.g. {dupes}. Keep one row each."
        )
    return df


def score(frames, season, salaries=None, votes=None, max_salary=MAX_SALARY):
    """Turn the raw nba_api tables into one scored row per player."""
    try:
        # ---- Join everything onto the per-game table
        adv_cols = [
            "PLAYER_ID",
            "TS_PCT",
            "USG_PCT",
            "NET_RATING",
            "AST_PCT",
            "AST_TO",
            "OFF_RATING",
            "DEF_RATING",
        ]
        df = frames["base"].merge(frames["adv"][adv_cols], on="PLAYER_ID", how="left")
        df = df[df["MIN"] >= MIN_MPG_SCORED].copy()
        if df.empty:
            raise LoaderError(f"No player averages {MIN_MPG_SCORED}+ minutes yet in {season}.")

        d = frames["defend"].rename(columns={"CLOSE_DEF_PERSON_ID": "PLAYER_ID"})
        df = df.merge(d[["PLAYER_ID", "PCT_PLUSMINUS", "D_FGA"]], on="PLAYER_ID", how="left")
        df = df.merge(frames["touches"][["PLAYER_ID", "TOUCHES"]], on="PLAYER_ID", how="left")
        onoff = frames["onoff"][["PLAYER_ID", "ON_NET", "OFF_NET"]].drop_duplicates("PLAYER_ID")
        df = df.merge(onoff, on="PLAYER_ID", how="left")
        idx = frames["index"].rename(columns={"PERSON_ID": "PLAYER_ID"})
        df = df.merge(
            idx[["PLAYER_ID", "POSITION"]].drop_duplicates("PLAYER_ID"), on="PLAYER_ID", how="left"
        )
    except KeyError as exc:
        raise LoaderError(
            f"A raw table is missing the column {exc}. If you're using the cache, "
            f"set USE_CACHE = False and run again."
        ) from None

    approximations = list(APPROX_BASE)

    # ---- Production Value (PV)
    ts = pct(df["TS_PCT"])
    playmaking = 0.5 * pct(df["AST_PCT"]) + 0.5 * pct(df["AST_TO"])
    on_off = pct(df["ON_NET"] - df["OFF_NET"])
    df["efficiency"] = 0.34 * ts + 0.23 * playmaking + 0.43 * on_off

    # Lower opponent FG% than expected is better; contesting more shots adds credit.
    def_versatility = 0.7 * pct(df["PCT_PLUSMINUS"], higher_is_better=False) + 0.3 * pct(
        df["D_FGA"]
    )
    workload = pct(df["MIN"] * df["USG_PCT"])
    carry_tax = pct(df["OFF_NET"], higher_is_better=False)  # team worse without him = heavier carry
    df["role_difficulty"] = 0.40 * def_versatility + 0.33 * workload + 0.27 * carry_tax

    league_off, league_def = df["OFF_RATING"].mean(), df["DEF_RATING"].mean()
    two_way = pct((df["OFF_RATING"] - league_off) + (league_def - df["DEF_RATING"]))
    df["versatility"] = (
        0.34 * pct(position_slots(df["POSITION"]))
        + 0.43 * two_way
        + 0.23 * pct(skill_diversity(df))
    )

    df["production_value"] = (
        0.35 * df["efficiency"] + 0.30 * df["role_difficulty"] + 0.35 * df["versatility"]
    )

    # ---- Investment Index (RI): Financial
    if salaries is not None:
        cols = [c for c in ["PLAYER_NAME", "SALARY", "MAX_ELIGIBLE"] if c in salaries.columns]
        df = df.merge(salaries[cols], on="PLAYER_NAME", how="left")
        df["SALARY"] = pd.to_numeric(df["SALARY"], errors="coerce")
        missing = df["SALARY"].isna()
        df.loc[missing, "SALARY"] = estimate_salary(df.loc[missing])
        if missing.any():
            approximations.append(
                f"Salary estimated for {int(missing.sum())} players not matched in the salary file"
            )
    else:
        df["SALARY"] = estimate_salary(df)
        approximations.append(
            "Salary is an estimated tier from minutes and scoring (no salary file given)"
        )
    if "MAX_ELIGIBLE" in df.columns:
        max_eligible = pd.to_numeric(df["MAX_ELIGIBLE"], errors="coerce").fillna(max_salary)
    else:
        max_eligible = pd.Series(max_salary, index=df.index)
        approximations.append("Max-eligible salary uses one league-wide max tier for every player")
    salary_share = (df["SALARY"] / max_eligible).clip(0, 1) * 100
    dollars_per_production = pct(df["SALARY"] / df["production_value"].clip(lower=1))
    df["financial"] = 0.65 * salary_share + 0.35 * dollars_per_production

    # ---- RI: Usage
    df["usage_cost"] = 0.40 * pct(df["USG_PCT"]) + 0.33 * pct(df["MIN"]) + 0.27 * pct(df["TOUCHES"])

    # ---- RI: Recognition
    aw = award_points(frames["awards"], season)
    df = df.merge(aw, on="PLAYER_ID", how="left")
    df["award_pts"] = pd.to_numeric(df["award_pts"], errors="coerce").fillna(0.0)
    df["allstar_pts"] = pd.to_numeric(df["allstar_pts"], errors="coerce").fillna(0.0)
    if votes is not None:
        df = df.merge(votes[["PLAYER_NAME", "VOTES"]], on="PLAYER_NAME", how="left")
        vote_score = pct(pd.to_numeric(df["VOTES"], errors="coerce").fillna(0))
    else:
        vote_score = df["allstar_pts"] / max(df["allstar_pts"].max(), 1e-9) * 100
        approximations.append(
            "All-Star votes use decayed All-Star selections (no votes file given)"
        )
    award_score = df["award_pts"] / max(df["award_pts"].max(), 1e-9) * 100
    df["recognition"] = 0.40 * vote_score + 0.60 * award_score

    df["investment_index"] = (
        0.40 * df["financial"] + 0.35 * df["usage_cost"] + 0.25 * df["recognition"]
    )

    # ---- Final score, rating and gates
    df["penalty_multiplier"] = [
        penalty(n, t) for n, t in zip(df["NET_RATING"].fillna(0), df["TS_PCT"].fillna(0))
    ]
    df["underrated_score"] = (
        df["production_value"] * df["penalty_multiplier"] / df["investment_index"].clip(lower=5)
    )
    df["rating"] = df["underrated_score"].map(tier)

    # The 30-game gate can't be met in November, so scale it to the games played so far.
    team_games = int(pd.to_numeric(frames["teams"]["GP"], errors="coerce").max())
    gp_gate = max(
        1,
        int(np.ceil(FULL_SEASON_GP_GATE * min(team_games, FULL_SEASON_GAMES) / FULL_SEASON_GAMES)),
    )
    if gp_gate < FULL_SEASON_GP_GATE:
        approximations.append(
            f"GP gate scaled to {gp_gate} games ({team_games} team games played; full season uses 30)"
        )
    df["gp_gate"] = gp_gate
    df["qualified"] = (df["GP"] >= gp_gate) & (df["MIN"] >= 15) & (df["production_value"] >= 50)

    # ---- Tidy into the BigQuery table's columns
    df = df.sort_values("underrated_score", ascending=False).reset_index(drop=True)
    df["league_rank"] = np.arange(1, len(df) + 1)
    df["SEASON"] = season
    df["formula_version"] = FORMULA_VERSION
    df["approximations"] = "; ".join(approximations)
    df["loaded_at"] = pd.Timestamp(dt.datetime.now(dt.timezone.utc))

    keep = [
        "SEASON",
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ABBREVIATION",
        "GP",
        "MIN",
        "PTS",
        "REB",
        "AST",
        "TS_PCT",
        "NET_RATING",
        "USG_PCT",
        "SALARY",
        "efficiency",
        "role_difficulty",
        "versatility",
        "production_value",
        "financial",
        "usage_cost",
        "recognition",
        "investment_index",
        "penalty_multiplier",
        "underrated_score",
        "rating",
        "qualified",
        "gp_gate",
        "league_rank",
        "formula_version",
        "approximations",
        "loaded_at",
    ]
    out = df[keep].copy()
    for c in [
        "efficiency",
        "role_difficulty",
        "versatility",
        "production_value",
        "financial",
        "usage_cost",
        "recognition",
        "investment_index",
    ]:
        out[c] = out[c].astype(float).round(2)
    out["underrated_score"] = out["underrated_score"].astype(float).round(3)
    for c in ["PLAYER_ID", "GP", "SALARY", "gp_gate", "league_rank"]:
        out[c] = out[c].astype("int64")
    for c in [
        "SEASON",
        "PLAYER_NAME",
        "TEAM_ABBREVIATION",
        "rating",
        "formula_version",
        "approximations",
    ]:
        out[c] = out[c].astype(object)
    out["qualified"] = out["qualified"].astype(bool)
    return out


def save_csv(df, season):
    """Write the scores next to this file. Explains the usual Excel lock problem."""
    path = os.path.join(HERE, f"nba_underrated_scores_{season}.csv")
    try:
        df.to_csv(path, index=False)
    except PermissionError:
        raise LoaderError(
            f"Couldn't save {path} because it's open in another program "
            f"(usually Excel). Close it and run again."
        ) from None
    log(f"Saved {len(df)} scored players to {path}")
    return path


# Columns the public dashboard reads, in order, and how many decimals each keeps.
PAGES_COLUMNS = {
    "PLAYER_ID": None,
    "PLAYER_NAME": None,
    "TEAM_ABBREVIATION": None,
    "GP": None,
    "MIN": 1,
    "PTS": 1,
    "REB": 1,
    "AST": 1,
    "TS_PCT": 3,
    "NET_RATING": 1,
    "USG_PCT": 3,
    "production_value": 1,
    "investment_index": 1,
    "penalty_multiplier": 2,
    "underrated_score": 3,
    "rating": None,
    "qualified": None,
    "gp_gate": None,
    "league_rank": None,
    "loaded_at": None,
}


def save_pages_csv(df, season):
    """Rewrite the public dashboard's data file: docs/data/player_scores_<season>.csv.

    The file holds only the columns the page shows, rounded for display.
    It's plain UTF-8 with Unix line endings, so git diffs stay small.
    """
    folder = os.path.normpath(os.path.join(HERE, "..", "docs", "data"))
    if not os.path.isdir(os.path.dirname(folder)):
        # No docs folder means this file isn't sitting in the repository's pipelines/ folder.
        raise LoaderError(
            f"Couldn't find the dashboard folder {os.path.dirname(folder)}.\n"
            "Fix: run the loader from the repository's pipelines folder, or set "
            "PAGES_EXPORT = False in SETTINGS."
        )
    path = os.path.join(folder, f"player_scores_{season}.csv")

    missing = [c for c in PAGES_COLUMNS if c not in df.columns]
    if missing:
        raise LoaderError(f"The scores are missing columns the dashboard needs: {missing}")

    out = df[list(PAGES_COLUMNS)].copy()
    out = out.sort_values("league_rank").reset_index(drop=True)
    for col, places in PAGES_COLUMNS.items():
        if places is not None:
            out[col] = out[col].astype(float).map(lambda v, p=places: f"{v:.{p}f}")
    out["qualified"] = out["qualified"].map(lambda v: "true" if bool(v) else "false")
    out["loaded_at"] = pd.to_datetime(out["loaded_at"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        os.makedirs(folder, exist_ok=True)
        out.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    except PermissionError:
        raise LoaderError(
            f"Couldn't save {path} because it's open in another program "
            f"(usually Excel). Close it and run again."
        ) from None
    except OSError as exc:
        raise LoaderError(f"Couldn't write the dashboard file {path}: {exc}") from None
    log(f"Updated the dashboard data file {path}. Commit and push it to refresh the page.")
    return path


# %% STAGE 3: LOAD INTO BIGQUERY
# ---------------------------------------------------------------------------
# Your project runs on BigQuery's free tier (the "sandbox"), which doesn't
# allow DELETE or INSERT statements. So the replace works without them:
#   1. Read every row of the OTHER seasons already in the table.
#   2. Add this season's fresh scores to them.
#   3. Load the combined rows with WRITE_TRUNCATE, which swaps the table's
#      contents in one step. If the load fails, the old rows stay untouched.
# Net effect: only this season's rows change. Other seasons ride along as-is.
#
# The free tier also deletes tables 60 days after their expiry is set, so each
# load pushes the table's expiry back out to about 60 days from today.

TABLE_KEEP_DAYS = 59


def load_bigquery(df, season):
    if df.empty:
        raise LoaderError("There are no scored rows to load, so BigQuery was left as it was.")
    if set(df["SEASON"].unique()) != {season}:
        raise LoaderError(
            "The scores contain more than one season, so BigQuery was left as it was."
        )

    bigquery = require("google.cloud.bigquery", "google-cloud-bigquery")
    require("pyarrow")
    require("db_dtypes", "db-dtypes")
    gexc = require("google.api_core.exceptions", "google-cloud-bigquery")
    auth_exc = require("google.auth.exceptions", "google-auth")

    try:
        client = bigquery.Client(project=PROJECT)
    except auth_exc.DefaultCredentialsError:
        raise LoaderError(
            "Google Cloud doesn't know who you are on this computer yet.\n"
            "Fix: open Anaconda Prompt (or a terminal) and run\n"
            "    gcloud auth application-default login\n"
            "sign in with the Google account that owns the project, then run this again.\n"
            "If 'gcloud' isn't recognised, install the Google Cloud CLI first."
        ) from None

    try:
        table = client.get_table(TABLE)
        names = [f.name for f in table.schema]

        # 1. Rows for every other season, kept exactly as they are.
        others = client.query(
            f"SELECT * FROM `{TABLE}` WHERE SEASON != @season",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("season", "STRING", season)]
            ),
        ).to_dataframe()
        if len(others):
            log(
                f"Keeping {len(others)} rows from other seasons: "
                f"{', '.join(sorted(others['SEASON'].unique()))}"
            )

        # 2. Combine, in the table's own column order.
        missing = [c for c in names if c not in df.columns]
        if missing:
            raise LoaderError(
                f"The scores are missing table column(s) {missing}, so BigQuery was left as it was."
            )
        combined = (
            pd.concat([others[names], df[names]], ignore_index=True) if len(others) else df[names]
        )

        # 3. Swap the table's contents in one load job.
        log(f"Loading {len(df)} rows for {season} into {TABLE} ...")
        job_config = bigquery.LoadJobConfig(schema=table.schema, write_disposition="WRITE_TRUNCATE")
        client.load_table_from_dataframe(combined, TABLE, job_config=job_config).result()

        count = client.get_table(TABLE).num_rows
        log(f"Done: {TABLE} now holds {count} rows ({len(df)} for {season}).")

        # Keep the free-tier table from expiring. A failure here doesn't undo the load.
        try:
            table = client.get_table(TABLE)
            table.expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=TABLE_KEEP_DAYS)
            client.update_table(table, ["expires"])
            log(
                f"Table expiry pushed to {table.expires:%b %d, %Y}. Run the loader before then to keep it."
            )
        except Exception as exc:
            log(
                f"  Couldn't push back the table's expiry ({type(exc).__name__}). "
                f"The scores loaded fine; check the expiry in the BigQuery console."
            )
        return count

    except auth_exc.RefreshError:
        raise LoaderError(
            "Your Google Cloud sign-in has expired.\n"
            "Fix: run   gcloud auth application-default login   again, then rerun this."
        ) from None
    except gexc.NotFound as exc:
        raise LoaderError(
            f"BigQuery couldn't find the project, dataset or table ({exc.message}).\n"
            f"Check PROJECT, DATASET and TABLE_NAME in SETTINGS. On the free tier, a table "
            f"also disappears once its 60-day expiry passes."
        ) from None
    except gexc.Forbidden as exc:
        raise LoaderError(
            f"BigQuery refused the write ({exc.message}).\n"
            "Usual causes: you're signed in with a different Google account than the project's "
            "owner, or the account lacks the BigQuery Data Editor and Job User roles."
        ) from None
    except gexc.BadRequest as exc:
        raise LoaderError(
            f"BigQuery rejected the data ({exc.message}).\n"
            "This usually means the table's columns no longer match the scores. "
            "The table was left as it was."
        ) from None
    except gexc.GoogleAPICallError as exc:
        raise LoaderError(
            f"BigQuery returned an error: {exc}. The table was left as it was."
        ) from None


# %% RUN: press F5 to run the whole file, or run this cell after the ones above
# ---------------------------------------------------------------------------


def run():
    """Fetch, score and load, stopping cleanly with an explanation on any known problem.

    Returns (frames, scores). Either can be None if the run stopped early.
    """
    frames, scores = None, None
    try:
        if not isinstance(SEASON, str) or len(SEASON) != 7 or SEASON[4] != "-":
            raise LoaderError(f"SEASON should look like '2026-27' (it's {SEASON!r}).")

        salaries = read_optional_csv(SALARY_FILE, ["PLAYER_NAME", "SALARY"], "salary")
        votes = read_optional_csv(VOTES_FILE, ["PLAYER_NAME", "VOTES"], "All-Star votes")

        frames = load_cache(SEASON) if USE_CACHE else None
        if frames is None:
            log(f"Pulling {SEASON} from stats.nba.com. This takes several minutes.")
            frames = fetch_frames(SEASON)
            save_cache(frames, SEASON)

        log("Scoring players ...")
        scores = score(frames, SEASON, salaries, votes)
        save_csv(scores, SEASON)
        if PAGES_EXPORT:
            save_pages_csv(scores, SEASON)

        top = scores.loc[
            scores["qualified"], ["PLAYER_NAME", "TEAM_ABBREVIATION", "underrated_score", "rating"]
        ]
        log(
            f"{len(scores)} players scored, {len(top)} qualified (GP gate {scores['gp_gate'].iloc[0]})."
        )
        print(top.head(10).to_string(index=False) if len(top) else "  No qualified players yet.")

        if DRY_RUN:
            log("DRY_RUN is on, so BigQuery was not touched.")
        elif PROJECT == "your-gcp-project-id":
            raise LoaderError(
                "PROJECT in SETTINGS is still the placeholder, so BigQuery was not touched.\n"
                "Fix: set PROJECT to your Google Cloud project ID, or set DRY_RUN = True "
                "to only score and save the CSV."
            )
        else:
            load_bigquery(scores, SEASON)

    except LoaderError as exc:
        print("\n" + "=" * 70 + "\nSTOPPED: " + str(exc) + "\n" + "=" * 70)
    except KeyboardInterrupt:
        print("\nSTOPPED: you interrupted the run. Nothing was written to BigQuery.")
    except Exception:
        print("\n" + "=" * 70)
        print("STOPPED: an unexpected error. Nothing was written to BigQuery unless the log above")
        print("says 'Done'. The details below are what to share if you want help:")
        traceback.print_exc()
        print("=" * 70)
    return frames, scores


if __name__ == "__main__":
    frames, scores = run()
