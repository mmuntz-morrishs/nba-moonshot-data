"""Offline tests of NBA.com HTML validation and provisional official-page comparisons."""
import copy
import json
import pathlib
import unittest

from official_roster_reconcile import TEAMS, parse_team_page, reconcile, page_url

AUDIT=json.loads((pathlib.Path(__file__).parent /
                  "published/roster_preflight_2027.json").read_text(encoding="utf-8"))

def html_table(names_and_ids):
    rows="\n".join(
       f'<tr><td><a href="/player/{pid or 1643000+i}">{name}</a></td>'
       '<td>4</td><td>G</td></tr>'
       for i,(name,pid) in enumerate(names_and_ids))
    return f'<html><body><table><thead><tr><th>Player</th><th>#</th><th>Pos</th></tr></thead><tbody>{rows}</tbody></table></body></html>'

def inputs():
    pages=[]
    for t in TEAMS:
        old=[p for p in AUDIT["players"] if p["team"]==t][:12]
        roster=[(p["player"],p.get("observed_nba_player_id") or p.get("seed_nba_player_id")) for p in old]
        parsed=parse_team_page(html_table(roster),t)
        pages.append({"team":t,"source_url":page_url(t),"retrieved_utc":"2026-10-13T21:00:00Z",
                      "http_status":200,"html_sha256":"f"*64,"players":parsed})
    return pages

class TestOfficialReconciliation(unittest.TestCase):
    def test_six_official_url_patterns(self):
        self.assertEqual(len(TEAMS),6)
        for t in TEAMS:self.assertRegex(page_url(t),r"^https://www\.nba\.com/team/16106127")

    def test_parse_table_with_player_links(self):
        r=parse_team_page(html_table([("Sample Player "+str(i),str(1643000+i)) for i in range(12)]),"BOS")
        self.assertEqual(len(r),12)
        self.assertEqual(r[0]["nba_player_id"],"1643000")

    def test_player_table_missing_must_fail(self):
        with self.assertRaisesRegex(ValueError,"Expected one NBA roster table"):
            parse_team_page("<html><table><thead><tr><th>Game</th></tr></thead></table></html>","BOS")

    def test_duplicate_roster_names_fail(self):
        people=[("John Smith",str(1643000+i)) for i in range(12)]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            parse_team_page(html_table(people),"BOS")

    def test_too_few_players_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"10-25"):
            parse_team_page(html_table([("Test Player", "1643000")]),"DET")

    def test_official_page_comparison_never_certifies_roster(self):
        r=reconcile(AUDIT,inputs(),checked_utc="2026-10-13T21:00:00Z")
        self.assertEqual(len(r["sources"]),6)
        self.assertEqual(r["counts"]["nba_page_players"],72)
        self.assertEqual(r["counts"]["prior_preseason_entries"],125)
        self.assertFalse(r["opening_night_final_roster_certified"])
        self.assertFalse(r["game_day_availability_certified"])
        self.assertFalse(r["paid_sgo_allowed"])
        self.assertEqual(r["source_kind"],"NBA_COM_CURRENT_TEAM_PAGE_NOT_FINAL_RELEASE")

    def test_bad_team_page_source_rejected(self):
        pages=inputs()
        pages[0]["source_url"]="https://example.com/roster"
        with self.assertRaisesRegex(ValueError,"source URL mismatch"):
            reconcile(AUDIT,pages)

    def test_missing_team_blocked(self):
        with self.assertRaisesRegex(ValueError,"Missing or duplicate NBA.com team page"):
            reconcile(AUDIT,inputs()[:5])

    def test_same_person_new_id_flagged(self):
        pages=inputs()
        old=pages[0]["players"][0]
        old["nba_player_id"]="9999999"
        r=reconcile(AUDIT,pages)
        self.assertTrue(any(p["status"]=="ID_CONFLICT_REVIEW" for p in r["players"]))
        self.assertFalse(r["paid_sgo_allowed"])

    def test_new_player_reported(self):
        pages=inputs()
        pages[0]["players"].append({"team":"BOS","player":"An Unlisted Rookie","nba_player_id":"1643999"})
        r=reconcile(AUDIT,pages)
        self.assertTrue(any(p["status"]=="NEW_NBA_PAGE_PLAYER_ID" for p in r["players"]))

    def test_different_page_nba_id_is_not_silently_merged(self):
        pages=inputs()
        idval=pages[0]["players"][0]["nba_player_id"]
        self.assertIsNotNone(idval)
        pages[1]["players"][0]["nba_player_id"]=idval
        r=reconcile(AUDIT,pages)
        self.assertTrue(any(p["status"]=="AMBIGUOUS_OR_DUPLICATE_NBA_ID" for p in r["players"]))
        self.assertTrue(any("Duplicate linked NBA ID" in q for q in r["issues"]))

    def test_page_absence_not_equal_waived(self):
        r=reconcile(AUDIT,inputs())
        self.assertGreater(len(r["prior_players_not_matched"]),0)
        self.assertTrue(all("does NOT prove waiver" in x["note"] for x in r["prior_players_not_matched"]))

    def test_has_no_automatic_expiration_certification(self):
        result=reconcile(AUDIT,inputs(),checked_utc="2026-10-20T20:00:00Z")
        self.assertFalse(result["opening_night_final_roster_certified"])

if __name__=="__main__":
    unittest.main(verbosity=2)
