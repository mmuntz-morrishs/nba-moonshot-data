"""Offline validation using the verified 2025-10-21 JSON published in this repo."""
import copy, json, pathlib, unittest
from export_bridge import normalize
F=json.loads((pathlib.Path(__file__).parent/"published/example_historical_bridge.json").read_text())

class BridgeTests(unittest.TestCase):
 def make(self,records=None,games=None,season=2026):
  return normalize(copy.deepcopy(F["games"] if games is None else games),
                   copy.deepcopy(F["player_game_logs"] if records is None else records),season)
 def test_ground_truth(self):
  r=self.make()
  self.assertEqual(r["counts"]["player_games"],10)
  expected={"201939":("GSW",9,3),"1627741":("GSW",10,5),
            "1630598":("OKC",5,2),"1630578":("HOU",8,5)}
  for p in r["player_game_logs"]:
   if p["player_id"] in expected:
    self.assertEqual((p["team"],p["three_pa"],p["three_pm"]),expected[p["player_id"]])
  self.assertTrue(r["demo_only"])
 def test_digest_matches_published(self):
  self.assertEqual(self.make()["records_sha256"],F["records_sha256"])
 def test_duplicate_row_blocked(self):
  data=copy.deepcopy(F["player_game_logs"]);data.append(data[0])
  with self.assertRaisesRegex(ValueError,"Duplicate"):self.make(records=data)
 def test_preseason_blocked(self):
  data=copy.deepcopy(F["games"]);data[0]["game_type"]="preseason"
  with self.assertRaisesRegex(ValueError,"Preseason"):self.make(games=data)
 def test_bad_season_blocked(self):
  with self.assertRaisesRegex(ValueError,"season/game"):self.make(season=2027)
 def test_makes_cannot_exceed_attempts(self):
  data=copy.deepcopy(F["player_game_logs"]);data[0]["three_pm"]=41
  with self.assertRaisesRegex(ValueError,"Invalid three"):self.make(records=data)
 def test_wrong_team_blocked(self):
  data=copy.deepcopy(F["player_game_logs"]);data[0]["team"]="DEN"
  with self.assertRaisesRegex(ValueError,"Team/opponent"):self.make(records=data)
 def test_2027_empty_never_live(self):
  v=normalize([],[],2027)
  self.assertTrue(v["demo_only"])
  self.assertEqual(v["roster_status"],"RECENT_GAME_ASSOCIATIONS_NOT_GAME_DAY_CONFIRMED")
 def test_roster_not_certified(self):
  v=normalize(F["games"],F["player_game_logs"],2026,[{"player_id":"201939","player":"Stephen Curry","team":"GSW"}])
  self.assertEqual(v["roster"][0]["verification"],"RECENT_GAME_ASSOCIATION_ONLY")

if __name__=="__main__":unittest.main(verbosity=2)
