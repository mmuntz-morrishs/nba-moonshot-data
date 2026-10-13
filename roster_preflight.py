#!/usr/bin/env python3
"""2026-27 Moonshot preseason NBA-ID preflight. Read-only DuckDB; manual publication."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import defaultdict

CATALOG = "https://basketball-data.billmill.org/nba/nba.duckdb"
TEAMS = ("BOS", "DET", "PHI", "NYK", "OKC", "SAS")
SEASON = 2027
SCHEMA = "nba-moonshot-roster-preflight/v1"

def require(ok, message):
    if not ok:
        raise ValueError(message)

def clean_name(value):
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())

def utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def validate_seed(seed):
    require(seed.get("schema") == "moonshot-roster-seed/v1", "Bad seed schema")
    require(seed.get("season") == SEASON, "Wrong seed season")
    require(set(seed.get("scope_teams", [])) == set(TEAMS), "Incomplete seed team scope")
    names, id_teams = set(), defaultdict(set)
    players = seed.get("players", [])
    require(len(players) >= 100, "Seed has too few entries")
    for s in players:
        team = str(s.get("team", ""))
        name = clean_name(s.get("player", ""))
        pid = s.get("nba_player_id")
        require(team in TEAMS and len(name) >= 3, "Invalid seed team/name")
        require((team, name) not in names, "Duplicated name/team in seed")
        names.add((team, name))
        if pid is not None:
            require(bool(re.fullmatch(r"[0-9]{1,12}", str(pid))), "Invalid seed NBA ID")
            id_teams[str(pid)].add(team)
    return players, {k: sorted(v) for k, v in id_teams.items() if len(v) > 1}

def check_observations(observations):
    seen = set()
    out = []
    for p in observations:
        pid = str(p["player_id"])
        team = str(p["team"])
        date = str(p["game_date"])
        gid = str(p["game_id"])
        game_type = str(p["game_type"])
        require(bool(re.fullmatch(r"[0-9]{1,12}", pid)), "Bad observed player NBA ID")
        require(team in TEAMS, "Unexpected NBA team in observations")
        require(bool(re.fullmatch(r"2026-[0-9]{2}-[0-9]{2}|2027-[0-9]{2}-[0-9]{2}", date)), "Bad season date")
        require(bool(re.fullmatch(r"00[12][0-9]{7}", gid)) and gid[3:5] == "26", "Invalid observed game ID: not 2026-27")
        require(game_type in ("preseason", "regular_season"), "Not preseason/regular season")
        require(len(clean_name(p["player"])) >= 3, "Missing observed player name")
        key = (gid, pid)
        require(key not in seen, "Duplicated observed player-game")
        seen.add(key)
        out.append({"player_id": pid, "player": str(p["player"]).strip(), "team": team,
                    "game_date": date, "game_id": gid, "game_type": game_type})
    return out

def assemble(seed, observations, checked_utc=None):
    seed_players, duplicate_seed_ids = validate_seed(seed)
    obs = check_observations(observations)
    # Most recent played game documents an association, NOT active roster status.
    by_id = defaultdict(list)
    by_name_team = defaultdict(set)
    for p in obs:
        by_id[p["player_id"]].append(p)
        by_name_team[(p["team"], clean_name(p["player"]))].add(p["player_id"])
    latest = {}
    for pid, rows in by_id.items():
        ordered = sorted(rows, key=lambda p:(p["game_date"], p["game_id"]), reverse=True)
        latest[pid] = ordered[0]
    result, referenced_ids = [], set()
    status_counts = defaultdict(int)
    for s in seed_players:
        team, name = str(s["team"]), str(s["player"])
        old_id = str(s["nba_player_id"]) if s.get("nba_player_id") is not None else None
        matched = latest.get(old_id) if old_id else None
        ids_for_name_team = by_name_team.get((team, clean_name(name)), set())
        status = "SEED_ONLY_NO_CURRENT_ID"
        selected_id = old_id
        note = "Not a game-day roster verification"
        evidence = None
        if old_id and old_id in duplicate_seed_ids:
            status = "SEED_DUPLICATE_ID_REVIEW"
        elif matched:
            evidence = matched
            referenced_ids.add(old_id)
            if matched["team"] != team:
                status = "PRESEASON_TEAM_CONFLICT"
            else:
                status = "ID_TEAM_OBSERVED_IN_GAME"
                if clean_name(name) != clean_name(matched["player"]):
                    note = "NBA ID/team match; different spelling/name requires review"
        elif len(ids_for_name_team) == 1:
            observed_id = next(iter(ids_for_name_team))
            evidence = latest[observed_id]
            referenced_ids.add(observed_id)
            if old_id and observed_id != old_id:
                selected_id = observed_id
                status = "HISTORICAL_ID_CONFLICT"
                note = "Conflicting NBA IDs: manual identity review required; do not auto-merge"
            elif not old_id:
                selected_id = observed_id
                status = "NAME_TEAM_MATCH_ID_RECOVERED"
        elif len(ids_for_name_team) > 1:
            status = "AMBIGUOUS_NAME_TEAM"
        elif old_id:
            status = "SEED_ID_NOT_SEEN_IN_CURRENT_GAMES"
        status_counts[status] += 1
        result.append({"team": team, "player": name, "seed_nba_player_id": old_id,
                       "observed_nba_player_id": selected_id,
                       "status": status, "last_game_date": evidence["game_date"] if evidence else None,
                       "last_game_id": evidence["game_id"] if evidence else None,
                       "last_game_type": evidence["game_type"] if evidence else None,
                       "note": note})
    # Also retain players on 2026-27 NBA team game logs not in the Oct 13 seed.
    for pid, p in latest.items():
        if pid in referenced_ids:
            continue
        if any(str(s.get("nba_player_id")) == pid for s in seed_players if s.get("nba_player_id")):
            continue
        status_counts["GAME_ONLY_NOT_ON_OCT13_SEED"] += 1
        result.append({"team": p["team"], "player": p["player"], "seed_nba_player_id": None,
                       "observed_nba_player_id": pid, "status": "GAME_ONLY_NOT_ON_OCT13_SEED",
                       "last_game_date": p["game_date"], "last_game_id": p["game_id"],
                       "last_game_type": p["game_type"],
                       "note": "Game participation is not an active opening-night roster confirmation"})
    result.sort(key=lambda p:(p["team"], p["player"].lower(), p["observed_nba_player_id"] or ""))
    games_by_team = defaultdict(set)
    ids_by_team = defaultdict(set)
    for p in obs:
        games_by_team[p["team"]].add(p["game_id"])
        ids_by_team[p["team"]].add(p["player_id"])
    coverage = {t:{"unique_ids_with_2026_27_game":len(ids_by_team[t]),
                   "games_with_observations":len(games_by_team[t])} for t in TEAMS}
    issues = ["Duplicate historical NBA ID assigned to multiple teams"] if duplicate_seed_ids else []
    issues += [f"No verified recent 2026-27 game participation for {t}" for t in TEAMS if not ids_by_team[t]]
    issues += [f"Review {status_counts[x]} {x} rows" for x in
               ("PRESEASON_TEAM_CONFLICT","HISTORICAL_ID_CONFLICT","AMBIGUOUS_NAME_TEAM")
               if status_counts[x]]
    payload = {"schema": SCHEMA, "season": SEASON, "checked_utc": checked_utc or utc_now(),
               "source": CATALOG, "reference_seed_date": seed.get("captured_utc"),
               "opening_night_teams": list(TEAMS),
               "status": "PROVISIONAL_ID_CROSSWALK_INCOMPLETE" if issues else "PROVISIONAL_ID_CROSSWALK_COVERED",
               "roster_certified": False, "game_day_active_certified": False, "paid_board_allowed": False,
               "note": "Preseason game team/ID association is not an official Oct 19 roster or Oct 20 availability confirmation.",
               "counts": {"reference_seed_players":len(seed_players),
                          "reference_seed_with_historical_id":sum(bool(s.get("nba_player_id")) for s in seed_players),
                          "2026_27_player_game_observations":len(obs),
                          "unique_observed_nba_ids":len(latest),
                          "output_entries":len(result), "statuses":dict(sorted(status_counts.items()))},
               "coverage":coverage, "warnings":issues, "duplicate_seed_ids":duplicate_seed_ids,
               "players":result}
    canonical = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",",":"))
    payload["players_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload

def remote_observations():
    import duckdb
    c = duckdb.connect()
    c.execute(f"ATTACH '{CATALOG}' AS nba (READ_ONLY)")
    # Never use team IDs from older seasons. Current-season games yield current NBA IDs.
    sql = """
      SELECT CAST(l.player_id AS VARCHAR), p.name, t.nba_abbrev,
             CAST(l.game_date AS VARCHAR), CAST(l.game_id AS VARCHAR), g.game_type
      FROM nba.player_game_logs l
      JOIN nba.games g ON l.season=g.season AND l.game_id=g.game_id
      JOIN nba.team_seasons t ON t.season=l.season AND t.team_id=l.team_id
      JOIN nba.player_seasons p ON p.season=l.season AND p.player_id=l.player_id
      WHERE l.season=2027 AND g.game_type IN ('preseason','regular_season')
        AND t.is_nba AND t.nba_abbrev IN ('BOS','DET','PHI','NYK','OKC','SAS')
        AND l.player_id IS NOT NULL
      ORDER BY l.game_date DESC, l.game_id DESC
    """
    rows = c.execute(sql).fetchall()
    return [{"player_id":pid,"player":name,"team":team,"game_date":date,
             "game_id":gid,"game_type":game_type}
            for pid,name,team,date,gid,game_type in rows]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed",default="reference/opening_six_roster_seed_2026-10-13.json")
    ap.add_argument("--out",default="published/roster_preflight_2027.json")
    args = ap.parse_args()
    seed = json.loads(pathlib.Path(args.seed).read_text(encoding="utf-8"))
    obs = remote_observations()
    require(len(obs)>0,"NO_CURRENT_SEASON_PRESEASON_GAME_LOGS: roster export blocked")
    report=assemble(seed,obs)
    target=pathlib.Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("ROSTER PREFLIGHT: "+report["status"])
    print("2026-27 observed rows: "+str(report["counts"]["2026_27_player_game_observations"]))
    print("Team coverage: "+json.dumps(report["coverage"]))
    print("Crosswalk statuses: "+json.dumps(report["counts"]["statuses"],sort_keys=True))
    print("Warnings: "+json.dumps(report["warnings"]))
    print("No NBA final roster certified. Paid board remains BLOCKED.")

if __name__ == "__main__":
    main()
