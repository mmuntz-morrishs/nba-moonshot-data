#!/usr/bin/env python3
"""Moonshot opening-week evidence checks. No automatic certification or betting.

Separate verified NBA ID crosswalk, post-deadline FINAL roster evidence, and
game-day injury-status evidence. Manually invoked, no network and no retries.
A PDF/HTML SHA proves file integrity, NOT source authenticity or transcription.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from collections import Counter,defaultdict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SEASON=2027
TEAMS=("BOS","DET","PHI","NYK","OKC","SAS")
GAMES=(
 ("BOS@DET","BOS","DET","2026-10-20T19:00:00+00:00"),
 ("PHI@NYK","PHI","NYK","2026-10-20T23:00:00+00:00"),
 ("OKC@SAS","OKC","SAS","2026-10-21T01:30:00+00:00"),
)
CUT=dt.datetime(2026,10,19,21,0,tzinfo=dt.timezone.utc) # 5 PM ET, 4 PM CT
CHICAGO=ZoneInfo("America/Chicago")
GAME_DATE=dt.date(2026,10,20)
ID_RE=re.compile(r"[1-9][0-9]{3,11}\Z")
CONTRACTS={"STANDARD","TWO_WAY","OTHER_REVIEW"}
DESIGNATIONS={"OUT","DOUBTFUL","QUESTIONABLE","PROBABLE","AVAILABLE",
              "NOT_YET_SUBMITTED","NOT_WITH_TEAM"}
SCHEMA_ROSTER="moonshot-official-release-evidence/v1"
SCHEMA_DAY="moonshot-game-day-injury-evidence/v1"

class EvidenceBlocked(ValueError): pass

def gate(ok,msg):
    if not ok:raise EvidenceBlocked(msg)

def utc():
    return dt.datetime.now(dt.timezone.utc)

def parseutc(s):
    gate(isinstance(s,str) and len(s)>10,"Missing ISO 8601 timestamp")
    try:
        x=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
        gate(x.tzinfo is not None,"Naive source timestamp")
        return x.astimezone(dt.timezone.utc)
    except (TypeError,ValueError):
        raise EvidenceBlocked("Invalid UTC source timestamp")

def genuine_nba_url(value):
    try:
        u=urlsplit(value)
        host=(u.hostname or "").lower()
    except (TypeError,ValueError):
        return False
    return u.scheme=="https" and (host=="nba.com" or host.endswith(".nba.com")) and bool(u.path)

def safe_doc(evidence,root):
    source=evidence.get("source_url","")
    gate(genuine_nba_url(source),"Must cite an HTTPS NBA-owned source URL")
    path=evidence.get("document_path","")
    gate(isinstance(path,str) and bool(path),"Missing document_path")
    base=pathlib.Path(root).resolve()
    target=(base/path).resolve()
    gate(base in target.parents and target.is_file(),"Evidence document not found in repository")
    gate(target.stat().st_size>=24 and target.stat().st_size<=50_000_000,
         "Evidence document missing, too small or too large")
    actual=hashlib.sha256(target.read_bytes()).hexdigest()
    gate(re.fullmatch("[0-9a-f]{64}",str(evidence.get("document_sha256",""))) is not None,
         "Missing SHA256 of official-source evidence")
    gate(actual==evidence["document_sha256"],"Document SHA256 mismatch")
    return {"source_url":source,"evidence_document":path,
            "document_sha256":actual,"document_bytes":target.stat().st_size,
            "document_origin_verified":False,
            "transcription_verified_against_document":False}

def load(path):
    p=pathlib.Path(path)
    gate(p.is_file(),"Required evidence manifest is not published")
    return json.loads(p.read_text(encoding="utf-8"))

def baseline_check(baseline,now,require_current):
    gate(baseline.get("schema")=="moonshot-nba-commonteamroster-reconciliation/v1",
         "Invalid cached NBA-ID baseline")
    gate(baseline.get("season")==SEASON,"Wrong baseline season")
    gate(baseline.get("counts",{}).get("current_nba_roster_players_6teams",0)>=100,
         "Incomplete six-team baseline")
    gate(baseline.get("counts",{}).get("source_unresolved_nba_ids_opening_six") == 0,
         "Baseline has unresolved NBA player IDs")
    gate(baseline.get("paid_sgo_allowed") is False,
         "Baseline incorrectly authorizes paid SGO")
    gate(set(baseline.get("team_counts",{}))==set(TEAMS),"Baseline missing NBA teams")
    if require_current:
        observed=parseutc(baseline.get("official_source_snapshot_fetched_utc"))
        gate(observed>=CUT,"Roster snapshot predates October 19 cutoff")
        gate(dt.timedelta(0)<=now-observed<=dt.timedelta(hours=24),
             "Roster source older than 24 hours or from the future")
    rows=baseline["players"]
    ids=defaultdict(list)
    for p in rows:
        pid=str(p.get("nba_player_id") or "")
        gate(p.get("team") in TEAMS and ID_RE.fullmatch(pid) is not None,
             "Baseline player/team/ID invalid")
        ids[pid].append(p["team"])
    gate(all(len(v)==1 for v in ids.values()),"Duplicate NBA ID in baseline")
    return {p["nba_player_id"]:p for p in rows}

def validate_official_release(manifest,baseline,root,now=None):
    now=now or utc()
    gate(now>=CUT,"WAIT_UNTIL_OCT19_4PM_CT")
    current=baseline_check(baseline,now,True)
    gate(manifest.get("schema")==SCHEMA_ROSTER and manifest.get("season")==SEASON,
         "Wrong release manifest schema/season")
    published=parseutc(manifest.get("source_published_utc"))
    gate(CUT<=published<=now,"Official roster evidence predates deadline or is future-dated")
    proof=safe_doc(manifest,root)
    rosters=manifest.get("rosters")
    gate(isinstance(rosters,dict) and set(rosters)==set(TEAMS),
         "Official release must explicitly contain all six teams")
    flat=[];seen=set()
    for team,people in rosters.items():
        gate(isinstance(people,list) and 12<=len(people)<=25,
             f"Implausible post-deadline team size for {team}")
        for p in people:
            pid=str(p.get("nba_player_id") or "")
            gate(ID_RE.fullmatch(pid) is not None,"Missing/malformed roster NBA ID")
            gate(pid not in seen,"Same NBA ID listed on multiple teams")
            seen.add(pid)
            gate(isinstance(p.get("player"),str) and len(p["player"].strip())>=3,
                 "Player name missing")
            gate(p.get("contract") in CONTRACTS,"Unknown contract type; use OTHER_REVIEW")
            flat.append({"team":team,"player":p["player"].strip(),"nba_player_id":pid,
                         "contract":p["contract"]})
    prior_ids=set(current);new_ids=seen-prior_ids
    changed=[]
    for p in flat:
        prior=current.get(p["nba_player_id"])
        if prior and prior["team"]!=p["team"]:
            changed.append({"player":p["player"],"nba_player_id":p["nba_player_id"],
                            "previous_team":prior["team"],"listed_team":p["team"]})
    pending_contract=[p for p in flat if p["contract"]=="OTHER_REVIEW"]
    return {"schema":"moonshot-roster-release-audit/v1","season":SEASON,
            "evaluated_utc":now.isoformat(),"source_published_utc":published.isoformat(),
            "source_evidence":proof,"state":"SOURCE_PRESENT_AWAITING_HUMAN_AUTHENTICITY_AND_TRANSCRIPTION_REVIEW",
            "official_final_rosters_certified":False,
            "game_day_availability_certified":False,"paid_sgo_allowed":False,
            "counts":{"source_listed":len(flat),"baseline":len(current),
                      "new_from_oct13":len(new_ids),
                      "not_listed_in_release":len(prior_ids-seen),
                      "team_moves":len(changed),
                      "unknown_contracts":len(pending_contract)},
            "unmatched_baseline":[current[pid] for pid in sorted(prior_ids-seen)],
            "team_moves":changed,
            "new_to_release":[p for p in flat if p["nba_player_id"] in new_ids],
            "contract_review":pending_contract,
            "rosters":rosters,
            "warnings":["Document checksum does NOT verify document authenticity or manually transcribed player list.",
                        "Compare the full PDF/HTML against the manifest before human certification.",
                        "No SGO request permitted even when automated checks pass."]}

def validate_gameday(report,final_roster,root,now=None):
    now=now or utc()
    gate(now.astimezone(CHICAGO).date()>=GAME_DATE,"WAIT_UNTIL_OCT20_CHICAGO")
    gate(report.get("schema")==SCHEMA_DAY and report.get("season")==SEASON,
         "Bad game-day report schema/season")
    gate(report.get("local_game_date")=="2026-10-20","Wrong game date")
    gate(final_roster.get("schema")=="moonshot-roster-release-audit/v1",
         "Missing final-roster comparison output")
    gate(final_roster.get("official_final_rosters_certified") is False,
         "Unexpected roster certification flag; do not enable betting")
    teams=final_roster.get("rosters",{})
    gate(set(teams)==set(TEAMS),"Incomplete roster evidence")
    by_team={t:{str(p["nba_player_id"]):p for p in people} for t,people in teams.items()}
    reports=report.get("games")
    gate(isinstance(reports,list) and len(reports)==3,"Require three game reports")
    keyed={}
    for entry in reports:
        label=entry.get("matchup")
        gate(label not in keyed,"Duplicate game report")
        keyed[label]=entry
    gate(set(keyed)=={g[0] for g in GAMES},"Missing opening-night matchup reports")
    output=[]; counts=Counter();uncertain=[];evidence=[]
    for label,away,home,kick in GAMES:
        g=keyed[label]
        tip=parseutc(kick)
        published=parseutc(g.get("report_published_utc"))
        gate(published<=now,"Future-dated injury source")
        gate(dt.timedelta(0)<=tip-published<=dt.timedelta(hours=12),
             f"Injury evidence stale for {label}: require report within 12h before tip")
        gate(now<=tip,"Cannot certify pregame availability after tipoff for "+label)
        gate(g.get("teams_reported")==[away,home],
             "Both matchup teams must be explicitly covered in "+label)
        proof=safe_doc(g,root)
        evidence.append({"matchup":label,"published_utc":published.isoformat(),**proof})
        listed={}
        for p in g.get("player_status",[]):
            team=str(p.get("team","")); pid=str(p.get("nba_player_id",""))
            status=p.get("designation")
            gate(team in (away,home) and pid in by_team[team],
                 "Injury player has wrong team, missing roster membership or unknown NBA ID")
            gate(status in DESIGNATIONS,"Invalid injury status")
            gate((team,pid) not in listed,"Duplicate injury player status")
            listed[team,pid]=status
        for team in (away,home):
            for pid,p in by_team[team].items():
                status=listed.get((team,pid),"NOT_LISTED_UNCONFIRMED")
                decision=("EXCLUDE" if status in ("OUT","DOUBTFUL","NOT_WITH_TEAM","NOT_YET_SUBMITTED")
                          else "REVIEW")
                counts[status]+=1
                if decision=="REVIEW":uncertain.append({"game":label,"team":team,"player":p["player"],
                                                         "nba_player_id":pid,"status":status})
                output.append({"matchup":label,"team":team,"player":p["player"],"nba_player_id":pid,
                               "report_status":status,"gate":decision,
                               "note":"No lineup confirmation, not an SGO authorization"})
    return {"schema":"moonshot-game-day-audit/v1","evaluated_utc":now.isoformat(),
            "local_game_date":"2026-10-20","state":"PENDING_MANUAL_SOURCE_REVIEW_AND_GAME_DAY_CONFIRMATION",
            "source_evidence":evidence,
            "roster_and_source_doc_human_verified":False,
            "game_day_availability_certified":False,"paid_sgo_allowed":False,
            "counts":dict(counts),"player_gates":output,"needs_review":uncertain,
            "warnings":["NBA injury-report absence is not proof a player is active.",
                        "Questionable, probable, listed available, and unlisted all require final confirmation.",
                        "Source document authenticity and transcription require human review.",
                        "Moonshot paid odds remain blocked pending separate explicit approval."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=["self-check","roster","game-day"],required=True)
    p.add_argument("--baseline",default="published/cached_nba_roster_reconciliation_2027.json")
    p.add_argument("--official-manifest",default="reference/official_final_rosters_2026-10-19.json")
    p.add_argument("--injury-manifest",default="reference/game_day_injuries_2026-10-20.json")
    p.add_argument("--roster-audit",default="published/opening_final_roster_audit_2027.json")
    p.add_argument("--out",default="")
    p.add_argument("--root",default=".")
    a=p.parse_args()
    now=utc()
    baseline=load(a.baseline)
    baseline_check(baseline,now,False)
    if a.mode=="self-check":
        print("SELF-CHECK PASS: historical ID baseline loads; calendar cutoffs preserved")
        print("OCT 19 16:00 America/Chicago: "+CUT.astimezone(CHICAGO).isoformat())
        print("OCT 20 game-day injury reports require explicit NBA-owned evidence")
        print("NO eligibility certification, 0 paid SGO calls, 0 sheet writes")
        return
    if a.mode=="roster":
        result=validate_official_release(load(a.official_manifest),baseline,a.root,now)
        path=a.out or a.roster_audit
    else:
        result=validate_gameday(load(a.injury_manifest),load(a.roster_audit),a.root,now)
        path=a.out or "published/opening_game_day_audit_2027.json"
    target=pathlib.Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"counts":result["counts"],
                      "paid_sgo_allowed":result["paid_sgo_allowed"]},sort_keys=True))
    print("PROVISIONAL SOURCE COMPARISON ONLY; official roster/availability NOT certified")

if __name__=="__main__":
    try:main()
    except EvidenceBlocked as e:
        raise SystemExit("CHECK BLOCKED (no audit published): "+str(e))
