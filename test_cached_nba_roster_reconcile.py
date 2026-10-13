"""Offline source format, NBA ID, freshness and paid-board guard tests."""
import copy
import datetime as dt
import json
import pathlib
import unittest
from cached_nba_roster_reconcile import (
    ALL_NBA_IDS, ID_TO_ABBREV, SCHEMA, SCOPE, normalize_payload, reconcile, rows_for_response
)

ROOT=pathlib.Path(__file__).parent
OLD=json.loads((ROOT/"published/roster_preflight_2027.json").read_text(encoding="utf-8"))
NOW=dt.datetime(2026,10,13,20,0,tzinfo=dt.timezone.utc)

def fixture():
    rosters={}
    for index,teamid in enumerate(sorted(ALL_NBA_IDS)):
        team=ID_TO_ABBREV[teamid]
        selected=[p for p in OLD["players"] if p["team"]==team][:12]
        entries=[]
        for i in range(12):
            if i<len(selected):
                p=selected[i]
                pid=p.get("observed_nba_player_id") or p.get("seed_nba_player_id")
                name=p["player"]
                if not pid:pid=str(900000000+index*100+i)
            else:
                pid=str(800000000+index*100+i)
                name=f"Mock Athlete {index}-{i}"
            entries.append([teamid,int(pid),name])
        rosters[teamid]={"resultSets":[{"name":"CommonTeamRoster",
                 "headers":["TEAM_ID","PLAYER_ID","PLAYER"],"rowSet":entries},
                 {"name":"Coaches","headers":["COACH"],"rowSet":[]}]}
    return {"fetched":"2026-10-13T12:00:00+00:00","rosters":rosters}

def processed():
    return normalize_payload(fixture(),now=NOW,sha256="9"*64)

class SnapshotTests(unittest.TestCase):
    def test_all_30_nba_ids(self):
        self.assertEqual(len(ALL_NBA_IDS),30)
        self.assertEqual(len(ID_TO_ABBREV),30)
        self.assertEqual(set(SCOPE),{"BOS","DET","PHI","NYK","OKC","SAS"})

    def test_extract_commonteamroster_not_coaches(self):
        inp=fixture()["rosters"][SCOPE["BOS"]]
        result=rows_for_response(inp,SCOPE["BOS"])
        self.assertEqual(len(result),12)
        self.assertEqual(result[0]["team"],"BOS")

    def test_all_30_complete_and_fresh(self):
        result=processed()
        self.assertEqual(len(result["team_rosters"]),30)
        self.assertEqual(result["source_age_hours"],8.0)

    def test_missing_team_refused(self):
        x=fixture()
        x["rosters"].pop(SCOPE["BOS"])
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_SOURCE"):
            normalize_payload(x,now=NOW)

    def test_old_snapshot_refused(self):
        x=fixture()
        x["fetched"]="2026-10-01T12:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"STALE_OR_FUTURE"):
            normalize_payload(x,now=NOW)

    def test_future_snapshot_refused(self):
        x=fixture()
        x["fetched"]="2026-10-20T12:00:00+00:00"
        with self.assertRaisesRegex(ValueError,"STALE_OR_FUTURE"):
            normalize_payload(x,now=NOW)

    def test_missing_nba_id_field_refused(self):
        x=fixture()
        x["rosters"][SCOPE["BOS"]]["resultSets"][0]["headers"]=["TEAM_ID","PERSON_ID","PLAYER"]
        with self.assertRaisesRegex(ValueError,"Missing NBA ID"):
            normalize_payload(x,now=NOW)

    def test_team_id_in_roster_row_refused_if_wrong(self):
        x=fixture()
        x["rosters"][SCOPE["BOS"]]["resultSets"][0]["rowSet"][0][0]=SCOPE["NYK"]
        with self.assertRaisesRegex(ValueError,"wrong NBA TEAM_ID"):
            normalize_payload(x,now=NOW)

    def test_duplicate_id_on_same_team_refused(self):
        x=fixture()
        rows=x["rosters"][SCOPE["BOS"]]["resultSets"][0]["rowSet"]
        rows[1][1]=rows[0][1]
        with self.assertRaisesRegex(ValueError,"Duplicate NBA player ID"):
            normalize_payload(x,now=NOW)

    def test_duplicate_id_across_teams_flagged(self):
        x=fixture()
        b=x["rosters"][SCOPE["BOS"]]["resultSets"][0]["rowSet"]
        p=x["rosters"][SCOPE["PHI"]]["resultSets"][0]["rowSet"]
        p[0][1]=b[0][1]
        result=normalize_payload(x,now=NOW)
        self.assertTrue(result["duplicate_player_ids_across_teams"])
        r=reconcile(OLD,result,checked=NOW)
        self.assertFalse(r["paid_sgo_allowed"])
        self.assertTrue(r["issues"])

    def test_compare_all_six_no_final_roster_claim(self):
        r=reconcile(OLD,processed(),checked=NOW)
        self.assertEqual(r["schema"],SCHEMA)
        self.assertEqual(r["counts"]["preseason_reference_players"],125)
        self.assertEqual(len(r["players"]),72)
        self.assertEqual(r["counts"]["current_team_roster_count_30teams"],30)
        self.assertFalse(r["official_oct19_final_rosters_certified"])
        self.assertFalse(r["oct20_game_day_availability_certified"])
        self.assertFalse(r["paid_sgo_allowed"])

    def test_roster_entry_missing_is_not_waiver(self):
        r=reconcile(OLD,processed(),checked=NOW)
        self.assertGreater(len(r["prior_players_not_matched"]),0)
        self.assertTrue(all("does not establish waiver" in x["note"] for x in r["prior_players_not_matched"]))

    def test_conflicting_seed_id_not_silently_replaced(self):
        x=fixture()
        # Modify first Boston player ID while keeping name unchanged.
        x["rosters"][SCOPE["BOS"]]["resultSets"][0]["rowSet"][0][1]=9999991
        r=reconcile(OLD,normalize_payload(x,now=NOW),checked=NOW)
        self.assertTrue(any(x["status"]=="ID_CONFLICT_MANUAL_REVIEW" for x in r["players"]))
        self.assertFalse(r["paid_sgo_allowed"])

    def test_source_not_a_final_league_release_even_after_cutoff(self):
        r=reconcile(OLD,processed(),checked=dt.datetime(2026,10,20,20,tzinfo=dt.timezone.utc))
        self.assertFalse(r["official_oct19_final_rosters_certified"])

if __name__=="__main__":
    unittest.main(verbosity=2)
