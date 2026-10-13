"""Zero-network unit tests for provisional Moonshot preseason roster and NBA IDs."""
import copy
import json
import pathlib
import unittest

from roster_preflight import assemble, clean_name, TEAMS

SEED = json.loads((pathlib.Path(__file__).parent /
                   "reference/opening_six_roster_seed_2026-10-13.json").read_text(encoding="utf-8"))

def sample():
    result=[]
    for i,team in enumerate(TEAMS):
        player=next(p for p in SEED["players"] if p["team"]==team and p["nba_player_id"])
        result.append({"player_id":player["nba_player_id"],"player":player["player"],
                       "team":team,"game_date":"2026-10-12",
                       "game_id":f"0012600{i:03d}","game_type":"preseason"})
    return result

class RosterPreflightTests(unittest.TestCase):
    def test_reference_is_exact_opening_six(self):
        self.assertEqual(len(SEED["players"]),125)
        self.assertEqual(sum(bool(p["nba_player_id"]) for p in SEED["players"]),93)
        self.assertEqual(set(p["team"] for p in SEED["players"]),set(TEAMS))

    def test_clean_names_unicode_and_punctuation(self):
        self.assertEqual(clean_name("Luka Dončić"),clean_name("Luka Doncic"))
        self.assertEqual(clean_name("Jr."),clean_name("Jr"))

    def test_current_preseason_id_matches_for_all_six(self):
        r=assemble(SEED,sample(),checked_utc="2026-10-13T19:00:00Z")
        self.assertEqual(r["counts"]["statuses"]["ID_TEAM_OBSERVED_IN_GAME"],6)
        self.assertEqual(len(r["coverage"]),6)
        self.assertTrue(all(v["unique_ids_with_2026_27_game"]==1 for v in r["coverage"].values()))
        self.assertEqual(r["status"],"PROVISIONAL_ID_CROSSWALK_INCOMPLETE")

    def test_paid_board_cannot_be_certified_by_preseason_games(self):
        r=assemble(SEED,sample())
        self.assertFalse(r["paid_board_allowed"])
        self.assertFalse(r["roster_certified"])
        self.assertFalse(r["game_day_active_certified"])

    def test_missing_historical_id_recovered_from_exact_name_team(self):
        x=next(p for p in SEED["players"] if p["team"]=="BOS" and p["nba_player_id"] is None)
        rows=sample()
        rows.append({"player_id":"1643998","player":x["player"],"team":"BOS",
                     "game_date":"2026-10-12","game_id":"0012600999","game_type":"preseason"})
        r=assemble(SEED,rows)
        p=next(p for p in r["players"] if p["team"]=="BOS" and p["player"]==x["player"])
        self.assertEqual(p["status"],"NAME_TEAM_MATCH_ID_RECOVERED")
        self.assertEqual(p["observed_nba_player_id"],"1643998")
        self.assertIsNone(p["seed_nba_player_id"])

    def test_moved_teams_conflict_is_not_silent(self):
        rows=sample()
        rows[0]["team"]="DET"
        r=assemble(SEED,rows)
        self.assertGreaterEqual(r["counts"]["statuses"]["PRESEASON_TEAM_CONFLICT"],1)
        self.assertFalse(r["paid_board_allowed"])
        self.assertTrue(any("PRESEASON_TEAM_CONFLICT" in w for w in r["warnings"]))

    def test_conflicting_observed_id_preserved_and_marked(self):
        rows=sample()
        q=next(p for p in SEED["players"] if p["team"]=="BOS" and p["nba_player_id"])
        rows[0]["player_id"]="1643997"
        r=assemble(SEED,rows)
        p=next(p for p in r["players"] if p["player"]==q["player"] and p["team"]=="BOS")
        self.assertEqual(p["status"],"HISTORICAL_ID_CONFLICT")
        self.assertEqual(p["observed_nba_player_id"],"1643997")
        self.assertEqual(p["seed_nba_player_id"],str(q["nba_player_id"]))

    def test_seed_only_not_marked_fresh(self):
        r=assemble(SEED,[])
        self.assertEqual(r["status"],"PROVISIONAL_ID_CROSSWALK_INCOMPLETE")
        self.assertEqual(r["counts"]["unique_observed_nba_ids"],0)
        self.assertEqual(r["counts"]["statuses"]["SEED_ID_NOT_SEEN_IN_CURRENT_GAMES"],93)

    def test_duplicate_game_player_rejected(self):
        rows=sample()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError,"Duplicated observed player-game"):
            assemble(SEED,rows)

    def test_preseason_only_and_regular_season_allowed(self):
        rows=sample()
        rows[0]["game_type"]="regular_season"
        rows[0]["game_id"]="0022600000"
        r=assemble(SEED,rows)
        self.assertEqual(r["counts"]["unique_observed_nba_ids"],6)
        rows[0]["game_type"]="playoffs"
        with self.assertRaisesRegex(ValueError,"Not preseason/regular season"):
            assemble(SEED,rows)

    def test_previous_season_game_id_rejected(self):
        rows=sample()
        rows[0]["game_id"]="0012500001"
        # Deliberately invalid season ID still matches shape; check date/game upstream.
        # Current parser enforces shape only; a proper 2026-27 preflight must also guard season digits.
        with self.assertRaisesRegex(ValueError,"Invalid observed game ID|2026-27"):
            assemble(SEED,rows)

    def test_unseeded_game_player_is_not_game_day_confirmed(self):
        rows=sample()
        rows.append({"player_id":"1643991","player":"New Test Player","team":"NYK",
                     "game_date":"2026-10-12","game_id":"0012600998","game_type":"preseason"})
        r=assemble(SEED,rows)
        q=next(p for p in r["players"] if p["observed_nba_player_id"]=="1643991")
        self.assertEqual(q["status"],"GAME_ONLY_NOT_ON_OCT13_SEED")
        self.assertFalse(r["roster_certified"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
