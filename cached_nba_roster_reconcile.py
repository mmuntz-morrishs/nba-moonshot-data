#!/usr/bin/env python3
"""Moonshot: manually fetch cached NBA CommonTeamRoster responses and reconcile IDs.

One public GET. Not a final league roster certification, game-day availability
check, paid odds request, sheet write, or scheduled activity.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.request import Request, urlopen

UPSTREAM="https://basketball-data.billmill.org/nba/raw/stats/2027/team_rosters.json.gz"
SCOPE={"BOS":"1610612738","DET":"1610612765","PHI":"1610612755",
       "NYK":"1610612752","OKC":"1610612760","SAS":"1610612759"}
SCHEMA="moonshot-nba-commonteamroster-reconciliation/v1"
ALL_NBA_IDS=set(str(i) for i in range(1610612737,1610612767))
ID_TO_ABBREV={
"1610612737":"ATL","1610612738":"BOS","1610612751":"BKN","1610612766":"CHA",
"1610612741":"CHI","1610612739":"CLE","1610612742":"DAL","1610612743":"DEN",
"1610612765":"DET","1610612744":"GSW","1610612745":"HOU","1610612754":"IND",
"1610612746":"LAC","1610612747":"LAL","1610612763":"MEM","1610612748":"MIA",
"1610612749":"MIL","1610612750":"MIN","1610612740":"NOP","1610612752":"NYK",
"1610612760":"OKC","1610612753":"ORL","1610612755":"PHI","1610612756":"PHX",
"1610612757":"POR","1610612758":"SAC","1610612759":"SAS","1610612761":"TOR",
"1610612762":"UTA","1610612764":"WAS"}
assert set(ID_TO_ABBREV)==ALL_NBA_IDS
MAX_AGE_HOURS=72

def need(ok,msg):
    if not ok: raise ValueError(msg)

def nname(name):
    return re.sub(r"[^a-z0-9]","",
      unicodedata.normalize("NFKD",str(name)).encode("ascii","ignore").decode("ascii").lower())

def utc():
    return dt.datetime.now(dt.timezone.utc)

def parse_timestamp(raw,now=None):
    now=now or utc()
    need(isinstance(raw,str),"Upstream roster fetched timestamp missing")
    try:
        value=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
        need(value.tzinfo is not None,"Roster fetched timestamp missing UTC offset")
        age=(now-value.astimezone(dt.timezone.utc)).total_seconds()/3600
    except (TypeError,ValueError) as exc:
        raise ValueError("Invalid upstream fetch timestamp: "+str(exc)) from exc
    need(-0.2<=age<=MAX_AGE_HOURS,
         f"STALE_OR_FUTURE_ROSTER_SNAPSHOT: age_hours={age:.1f}, max={MAX_AGE_HOURS}")
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),round(age,2)

def rows_for_response(data,team_id):
    need(isinstance(data,dict),"Non-JSON team roster response")
    sets=data.get("resultSets")
    if isinstance(sets,list):
        selected=next((q for q in sets if q.get("name")=="CommonTeamRoster"),None)
        if selected is None:
            selected=sets[0] if len(sets)==1 else None
    elif isinstance(sets,dict):
        selected=sets
    else:
        selected=None
    need(isinstance(selected,dict),"NBA CommonTeamRoster result set missing: "+team_id)
    headers=selected.get("headers")
    raw=selected.get("rowSet")
    need(isinstance(headers,list) and isinstance(raw,list),"Malformed roster table: "+team_id)
    need("PLAYER_ID" in headers and "PLAYER" in headers,"Missing NBA ID/player fields: "+team_id)
    i_id,i_name=headers.index("PLAYER_ID"),headers.index("PLAYER")
    i_team=headers.index("TeamID") if "TeamID" in headers else (headers.index("TEAM_ID") if "TEAM_ID" in headers else None)
    output=[]
    seen=set()
    for item in raw:
        need(isinstance(item,list) and len(item)==len(headers),"Malformed roster row: "+team_id)
        pid=str(item[i_id]) if item[i_id] is not None else ""
        pname=str(item[i_name] or "").strip()
        need(bool(re.fullmatch(r"\d{5,12}",pid)),f"Invalid NBA player ID for {team_id}")
        need(len(nname(pname))>=3,f"Invalid NBA player name for {team_id}")
        if i_team is not None and item[i_team] is not None:
            need(str(item[i_team])==team_id,"Roster row has wrong NBA TEAM_ID")
        need(pid not in seen,"Duplicate NBA player ID on same roster "+team_id)
        seen.add(pid)
        output.append({"team":ID_TO_ABBREV[team_id],"team_id":team_id,"player":pname,
                       "nba_player_id":pid})
    need(10<=len(output)<=30,f"Implausible NBA team roster size: {team_id} has {len(output)}")
    return output

def normalize_payload(payload,now=None,sha256=""):
    need(isinstance(payload,dict),"Source payload not an object")
    teams=payload.get("rosters")
    need(isinstance(teams,dict) and set(teams)==ALL_NBA_IDS,
         "INCOMPLETE_SOURCE: require exactly 30 official NBA team IDs")
    captured,age=parse_timestamp(payload.get("fetched"),now)
    full={}
    for team_id in sorted(teams):
        full[ID_TO_ABBREV[team_id]]=rows_for_response(teams[team_id],team_id)
    ids=defaultdict(list)
    for team,roster in full.items():
        for p in roster: ids[p["nba_player_id"]].append(team)
    duplicate_ids={k:sorted(v) for k,v in ids.items() if len(v)>1}
    return {"source":UPSTREAM,"source_sha256":sha256,
            "source_fetched_utc":captured,"source_age_hours":age,
            "team_rosters":full, "duplicate_player_ids_across_teams":duplicate_ids}

def fetch_source():
    req=Request(UPSTREAM,headers={"Accept":"application/octet-stream","User-Agent":"Moonshot-Roster-Audit/1.0"})
    with urlopen(req,timeout=35) as res:  # single GET, no retry
        need(res.status==200,"Roster source HTTP "+str(res.status))
        raw=res.read(15000001)
    need(len(raw)<15000001,"Roster source too large")
    need(raw[:2]==b"\x1f\x8b","Roster snapshot is not gzip")
    data=gzip.decompress(raw)
    need(len(data)<=25000000,"Decompressed roster too large")
    return json.loads(data.decode("utf-8")),hashlib.sha256(raw).hexdigest()

def reconcile(previous,snapshot,checked=None):
    need(previous.get("schema")=="nba-moonshot-roster-preflight/v1","Wrong prior preflight schema")
    need(previous.get("season")==2027,"Wrong prior season")
    need(set(previous.get("opening_night_teams",[]))==set(SCOPE),"Missing opening-night teams")
    prev=previous.get("players",[])
    need(len(prev)==125,"Unexpected Oct 13 baseline count")
    all30=snapshot["team_rosters"]
    need(set(SCOPE).issubset(all30),"Missing NBA team roster(s)")
    prev_by_team_name={}
    for p in prev:
        team,name=p["team"],nname(p["player"])
        need((team,name) not in prev_by_team_name,"Duplicate historical team/name")
        prev_by_team_name[team,name]=p
    official_by_id=defaultdict(list)
    for team, roster in all30.items():
        for p in roster:official_by_id[p["nba_player_id"]].append(p)
    six_rows=[];status=Counter();matched_prev=set();official_only=[];missing=[]
    for team in SCOPE:
        for current in all30[team]:
            pid,name=current["nba_player_id"],current["player"]
            old=prev_by_team_name.get((team,nname(name)))
            same_id_prior=[p for p in prev if p["team"]==team and
                           (p.get("observed_nba_player_id") or p.get("seed_nba_player_id"))==pid]
            if not old and len(same_id_prior)==1:old=same_id_prior[0]
            prior_id=(str(old.get("observed_nba_player_id") or old.get("seed_nba_player_id"))
                      if old and (old.get("observed_nba_player_id") or old.get("seed_nba_player_id")) else None)
            if pid in snapshot["duplicate_player_ids_across_teams"]:
                state="DUPLICATE_NBA_ID_ACROSS_30_TEAMS"
            elif old and prior_id and pid!=prior_id:
                state="ID_CONFLICT_MANUAL_REVIEW"
            elif old:
                state="NBA_ID_AND_TEAM_MATCH" if prior_id else "NBA_ID_RECOVERED_FROM_TEAM_ROSTER"
                matched_prev.add((team,nname(old["player"])))
            else:
                state="NEW_ON_NBA_TEAM_ROSTER"
                official_only.append({"team":team,"player":name,"nba_player_id":pid})
            status[state]+=1
            six_rows.append({"team":team,"player":name,"nba_player_id":pid,
                             "prior_nba_id":prior_id,"status":state,
                             "source":UPSTREAM,
                             "note":"NBA CommonTeamRoster list only; not a final roster/availability confirmation"})
    for p in prev:
        key=(p["team"],nname(p["player"]))
        if key in matched_prev:continue
        pid=str(p.get("observed_nba_player_id") or p.get("seed_nba_player_id") or "")
        located=[q["team"] for q in official_by_id.get(pid,[]) if q["team"]!=p["team"]]
        state="POSSIBLE_TEAM_CHANGE" if located else "NOT_ON_CURRENT_TEAM_ROSTER_SNAPSHOT"
        status[state]+=1
        missing.append({"prior_team":p["team"],"player":p["player"],"prior_nba_id":pid or None,
                        "now_listed_elsewhere":sorted(located),"status":state,
                        "note":"Not listed does not establish waiver, injury, or ineligibility"})
    issues=[]
    if snapshot["duplicate_player_ids_across_teams"]:
        issues.append("Same NBA player ID appears on multiple current NBA team rosters")
    for s in ["ID_CONFLICT_MANUAL_REVIEW","DUPLICATE_NBA_ID_ACROSS_30_TEAMS"]:
        if status[s]:issues.append(f"{status[s]} {s}")
    return {"schema":SCHEMA,"season":2027,"checked_utc":(checked or utc()).isoformat(),
            "source_kind":"CACHED_NBA_STATS_COMMON_TEAM_ROSTER_30_TEAMS",
            "source_url":snapshot["source"],"source_sha256":snapshot["source_sha256"],
            "official_source_snapshot_fetched_utc":snapshot["source_fetched_utc"],
            "source_age_hours":snapshot["source_age_hours"],
            "opening_night_teams":list(SCOPE),
            "official_nba_team_roster_snapshot_parsed":True,
            "official_oct19_final_rosters_certified":False,
            "oct20_game_day_availability_certified":False,
            "paid_sgo_allowed":False,
            "notes":["This is an NBA API CommonTeamRoster snapshot mirrored by a third-party NBA-data publisher.",
                     "NBA CommonTeamRoster is not proof of Oct 19 final league roster submission or Oct 20 availability.",
                     "No paid SGO, no Google Sheet writes, no automatic retries or scheduled triggers."],
            "counts":{"preseason_reference_players":len(prev),
                      "current_nba_roster_players_6teams":len(six_rows),
                      "current_team_roster_count_30teams":len(all30),
                      "new_on_current_six_team_rosters":len(official_only),
                      "not_matched_to_current_team_roster":len(missing),
                      "statuses":dict(sorted(status.items()))},
            "team_counts":{t:len(all30[t]) for t in SCOPE},
            "duplicate_player_ids_across_teams":snapshot["duplicate_player_ids_across_teams"],
            "issues":issues,"players":six_rows,
            "new_players":official_only,"prior_players_not_matched":missing}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--preflight",default="published/roster_preflight_2027.json")
    parser.add_argument("--out",default="published/cached_nba_roster_reconciliation_2027.json")
    args=parser.parse_args()
    prior=json.loads(pathlib.Path(args.preflight).read_text(encoding="utf-8"))
    payload,hashval=fetch_source()
    snapshot=normalize_payload(payload,sha256=hashval)
    output=reconcile(prior,snapshot)
    target=pathlib.Path(args.out)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("CACHED NBA TEAM ROSTERS: source age "+str(snapshot["source_age_hours"])+"h; all 30 verified")
    print("OPENING SIX: "+json.dumps(output["team_counts"]))
    print("STATUS COUNTS: "+json.dumps(output["counts"]["statuses"]))
    print("ISSUES: "+json.dumps(output["issues"]))
    print("FINAL OCT 19 ROSTER: NOT CERTIFIED; paid SGO board BLOCKED.")

if __name__=="__main__":main()
