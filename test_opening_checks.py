"""No-network tests for Oct 19 official final-roster / Oct 20 availability gates.

All mock source URLs and proof bytes are synthetic; these tests do NOT certify
an NBA source, actual final roster, player health, or paid betting eligibility.
"""
import copy
import datetime as dt
import hashlib
import json
import pathlib
import tempfile
import unittest
from opening_checks import (
 CUT, GAMES, TEAMS, EvidenceBlocked, baseline_check, genuine_nba_url, parseutc,
 validate_official_release, validate_gameday, SCHEMA_DAY, SCHEMA_ROSTER,CHICAGO
)

REPO=pathlib.Path(__file__).resolve().parent
BASELINE=json.loads((REPO/"published/cached_nba_roster_reconciliation_2027.json").read_text(encoding="utf-8"))
NOW_ROSTER=dt.datetime(2026,10,19,22,0,tzinfo=dt.timezone.utc)
NOW_DAY=dt.datetime(2026,10,20,16,0,tzinfo=dt.timezone.utc)

class OpeningChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=pathlib.Path(self.tmp.name)
        doc=self.root/"mock_nba_report.txt"
        doc.write_text("SYNTHETIC TEST DOCUMENT: not an NBA roster release or injury report.\n",
                       encoding="utf-8")
        self.proof={"source_url":"https://pr.nba.com/synthetic-test-only",
                    "document_path":doc.name,
                    "document_sha256":hashlib.sha256(doc.read_bytes()).hexdigest()}
        self.baseline=copy.deepcopy(BASELINE)
        self.baseline["official_source_snapshot_fetched_utc"]="2026-10-19T21:15:00Z"
        rosters={}
        for team in TEAMS:
            selected=[p for p in BASELINE["players"] if p["team"]==team][:15]
            rosters[team]=[{"nba_player_id":p["nba_player_id"],"player":p["player"],
                            "contract":"STANDARD"} for p in selected]
        self.roster_manifest={"schema":SCHEMA_ROSTER,"season":2027,
              "source_published_utc":"2026-10-19T21:30:00Z","rosters":rosters,**self.proof}
        self.roster_audit=validate_official_release(self.roster_manifest,self.baseline,
                                                    self.root,NOW_ROSTER)
        self.injury_manifest={"schema":SCHEMA_DAY,"season":2027,
              "local_game_date":"2026-10-20","games":[]}
        for i,(match,away,home,_) in enumerate(GAMES):
            self.injury_manifest["games"].append(
                {"matchup":match,"report_published_utc":(
                   "2026-10-20T10:00:00Z" if i==0 else
                   "2026-10-20T13:00:00Z" if i==1 else
                   "2026-10-20T15:00:00Z"),
                 "teams_reported":[away,home],"player_status":[],**self.proof})

    def tearDown(self):
        self.tmp.cleanup()

    def test_cutoff_in_chicago(self):
        self.assertEqual(CUT.astimezone(CHICAGO).strftime("%Y-%m-%d %H:%M"),"2026-10-19 16:00")

    def test_unapproved_url_rejected(self):
        self.assertTrue(genuine_nba_url("https://pr.nba.com/a-report"))
        self.assertFalse(genuine_nba_url("https://nba.com.evil.example/roster"))
        self.assertFalse(genuine_nba_url("http://nba.com/a-report"))

    def test_roster_before_deadline_is_blocked(self):
        with self.assertRaisesRegex(EvidenceBlocked,"WAIT_UNTIL"):
            validate_official_release(self.roster_manifest,self.baseline,self.root,CUT-dt.timedelta(seconds=1))

    def test_roster_cached_baseline_before_deadline_is_blocked(self):
        prev=copy.deepcopy(self.baseline)
        prev["official_source_snapshot_fetched_utc"]="2026-10-13T20:19:31Z"
        with self.assertRaisesRegex(EvidenceBlocked,"predates"):
            validate_official_release(self.roster_manifest,prev,self.root,NOW_ROSTER)

    def test_stale_final_baseline_is_blocked(self):
        prev=copy.deepcopy(self.baseline)
        with self.assertRaisesRegex(EvidenceBlocked,"older than 24"):
            validate_official_release(self.roster_manifest,prev,self.root,
               NOW_ROSTER+dt.timedelta(hours=25))

    def test_source_published_before_cutoff_blocked(self):
        d=copy.deepcopy(self.roster_manifest)
        d["source_published_utc"]="2026-10-19T20:59:59Z"
        with self.assertRaisesRegex(EvidenceBlocked,"predates deadline"):
            validate_official_release(d,self.baseline,self.root,NOW_ROSTER)

    def test_missing_evidence_document_blocked(self):
        d=copy.deepcopy(self.roster_manifest);d["document_path"]="not_here.pdf"
        with self.assertRaisesRegex(EvidenceBlocked,"document not found"):
            validate_official_release(d,self.baseline,self.root,NOW_ROSTER)

    def test_bad_sha_blocked(self):
        d=copy.deepcopy(self.roster_manifest);d["document_sha256"]="0"*64
        with self.assertRaisesRegex(EvidenceBlocked,"SHA256 mismatch"):
            validate_official_release(d,self.baseline,self.root,NOW_ROSTER)

    def test_roster_separate_source_proof_cannot_certify_itself(self):
        a=self.roster_audit
        self.assertEqual(a["counts"]["source_listed"],90)
        self.assertFalse(a["source_evidence"]["document_origin_verified"])
        self.assertFalse(a["source_evidence"]["transcription_verified_against_document"])
        self.assertFalse(a["official_final_rosters_certified"])
        self.assertFalse(a["paid_sgo_allowed"])

    def test_roster_missing_team_refused(self):
        d=copy.deepcopy(self.roster_manifest);del d["rosters"]["NYK"]
        with self.assertRaisesRegex(EvidenceBlocked,"six teams"):
            validate_official_release(d,self.baseline,self.root,NOW_ROSTER)

    def test_duplicate_nba_id_refused(self):
        d=copy.deepcopy(self.roster_manifest)
        d["rosters"]["PHI"][0]["nba_player_id"]=d["rosters"]["BOS"][0]["nba_player_id"]
        with self.assertRaisesRegex(EvidenceBlocked,"Same NBA ID"):
            validate_official_release(d,self.baseline,self.root,NOW_ROSTER)

    def test_contract_unknown_must_be_flagged(self):
        d=copy.deepcopy(self.roster_manifest)
        d["rosters"]["BOS"][0]["contract"]="OTHER_REVIEW"
        r=validate_official_release(d,self.baseline,self.root,NOW_ROSTER)
        self.assertEqual(r["counts"]["unknown_contracts"],1)
        self.assertFalse(r["official_final_rosters_certified"])

    def test_game_day_before_local_date_blocked(self):
        with self.assertRaisesRegex(EvidenceBlocked,"WAIT_UNTIL_OCT20_CHICAGO"):
            validate_gameday(self.injury_manifest,self.roster_audit,self.root,
                             dt.datetime(2026,10,19,23,0,tzinfo=dt.timezone.utc))

    def test_game_day_missing_matchup_blocked(self):
        d=copy.deepcopy(self.injury_manifest)
        d["games"].pop()
        with self.assertRaisesRegex(EvidenceBlocked,"three game reports"):
            validate_gameday(d,self.roster_audit,self.root,NOW_DAY)

    def test_game_day_source_stale_blocked(self):
        d=copy.deepcopy(self.injury_manifest)
        d["games"][0]["report_published_utc"]="2026-10-18T10:00:00Z"
        with self.assertRaisesRegex(EvidenceBlocked,"stale"):
            validate_gameday(d,self.roster_audit,self.root,NOW_DAY)

    def test_game_day_unrostered_id_blocked(self):
        d=copy.deepcopy(self.injury_manifest)
        d["games"][0]["player_status"].append(
            {"team":"BOS","nba_player_id":"9999999","designation":"OUT"})
        with self.assertRaisesRegex(EvidenceBlocked,"unknown NBA ID"):
            validate_gameday(d,self.roster_audit,self.root,NOW_DAY)

    def test_game_day_out_is_exclude_questionable_is_review(self):
        d=copy.deepcopy(self.injury_manifest)
        p=self.roster_manifest["rosters"]["BOS"]
        d["games"][0]["player_status"]=[
            {"team":"BOS","nba_player_id":p[0]["nba_player_id"],"designation":"OUT"},
            {"team":"BOS","nba_player_id":p[1]["nba_player_id"],"designation":"QUESTIONABLE"}]
        result=validate_gameday(d,self.roster_audit,self.root,NOW_DAY)
        self.assertEqual(result["counts"]["OUT"],1)
        self.assertEqual(result["counts"]["QUESTIONABLE"],1)
        out=next(x for x in result["player_gates"] if x["nba_player_id"]==p[0]["nba_player_id"])
        self.assertEqual(out["gate"],"EXCLUDE")
        self.assertFalse(result["paid_sgo_allowed"])

    def test_game_day_unlisted_never_available(self):
        result=validate_gameday(self.injury_manifest,self.roster_audit,self.root,NOW_DAY)
        self.assertEqual(result["counts"]["NOT_LISTED_UNCONFIRMED"],90)
        self.assertTrue(all(p["gate"]=="REVIEW" for p in result["player_gates"]))
        self.assertFalse(result["game_day_availability_certified"])

    def test_game_day_after_earliest_tipoff_blocked(self):
        late=dt.datetime(2026,10,20,19,1,tzinfo=dt.timezone.utc)
        with self.assertRaisesRegex(EvidenceBlocked,"after tipoff"):
            validate_gameday(self.injury_manifest,self.roster_audit,self.root,late)

    def test_game_day_duplicate_status_blocked(self):
        d=copy.deepcopy(self.injury_manifest)
        p=self.roster_manifest["rosters"]["BOS"][0]
        entry={"team":"BOS","nba_player_id":p["nba_player_id"],"designation":"OUT"}
        d["games"][0]["player_status"]=[entry,dict(entry)]
        with self.assertRaisesRegex(EvidenceBlocked,"Duplicate injury"):
            validate_gameday(d,self.roster_audit,self.root,NOW_DAY)

    def test_game_day_no_official_roster_document_blocked(self):
        invalid=copy.deepcopy(self.roster_audit);del invalid["rosters"]["DET"]
        with self.assertRaisesRegex(EvidenceBlocked,"Incomplete roster"):
            validate_gameday(self.injury_manifest,invalid,self.root,NOW_DAY)

if __name__=="__main__":
    unittest.main(verbosity=2)
