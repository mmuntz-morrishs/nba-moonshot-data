#!/usr/bin/env python3
"""Manual-only NBA.com team-page roster reconciliation. NO SGO, NO sheet writes.

An NBA.com page listing is official-source evidence of listed players, NOT
an NBA Oct 19 certified opening-day roster or Oct 20 game-day availability.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

TEAMS={"BOS":1610612738,"DET":1610612765,"PHI":1610612755,
       "NYK":1610612752,"OKC":1610612760,"SAS":1610612759}
SCHEMA="nba-moonshot-official-page-reconciliation/v1"
SOURCE_KIND="NBA_COM_CURRENT_TEAM_PAGE_NOT_FINAL_RELEASE"

def fail(ok,msg):
    if not ok: raise ValueError(msg)

def norm(name):
    return re.sub(r"[^a-z0-9]","",
        unicodedata.normalize("NFKD",str(name)).encode("ascii","ignore").decode("ascii").lower())

def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def page_url(team):
    return "https://www.nba.com/team/"+str(TEAMS[team])

def parse_team_page(html,team):
    """Require an actual Player/Pos NBA roster table; never extract from schedule."""
    fail(team in TEAMS,"Unexpected team")
    soup=BeautifulSoup(html,"html.parser")
    tables=[]
    for table in soup.find_all("table"):
        heads=[h.get_text(" ",strip=True).lower() for h in table.select("thead th")]
        if not heads:
            tr=table.find("tr")
            heads=[h.get_text(" ",strip=True).lower() for h in tr.find_all("th")] if tr else []
        if heads and ("player" in heads[0] or heads[0]=="name") and any("pos"==h or "position" in h for h in heads):
            tables.append(table)
    fail(len(tables)==1,f"Expected one NBA roster table for {team}, found {len(tables)}")
    table=tables[0]
    players=[]
    seen_names=set()
    for tr in table.select("tbody tr"):
        cells=tr.find_all("td",recursive=False)
        if not cells: continue
        first=cells[0]
        a=None
        for link in first.find_all("a",href=True):
            if re.search(r"/player(?:s)?/[0-9]{5,12}(?:[/?#]|$)",link["href"]):
                a=link;break
        if a is None: a=first.find("a")
        name=(a.get_text(" ",strip=True) if a else first.get_text(" ",strip=True))
        name=re.sub(r"\s+"," ",name).strip()
        fail(3<=len(norm(name))<=80,f"Invalid official roster name for {team}: {name!r}")
        pid=None
        if a:
            m=re.search(r"/player(?:s)?/([0-9]{5,12})(?:[/?#]|$)",a.get("href",""))
            if m: pid=m.group(1)
        key=norm(name)
        fail(key not in seen_names,f"Duplicate NBA.com player name for {team}: {name}")
        seen_names.add(key)
        players.append({"team":team,"player":name,"nba_player_id":pid})
    fail(10<=len(players)<=25,f"NBA.com table for {team} has {len(players)} players (need 10-25)")
    return players

def fetch_official_pages():
    out=[]
    for team in TEAMS:
        url=page_url(team)
        r=requests.get(url,timeout=22,headers={
            "User-Agent":"Mozilla/5.0 (compatible; MoonshotManualRosterAudit/0.1; +https://github.com/mmuntz-morrishs/nba-moonshot-data)",
            "Accept":"text/html"})
        fail(r.status_code==200,f"NBA.com HTTP {r.status_code} at {url} — stop, do not substitute a roster")
        ct=r.headers.get("content-type","").lower()
        fail("html" in ct,f"Unexpected content type {ct} at {url}")
        players=parse_team_page(r.text,team)
        out.append({"team":team,"source_url":url,"retrieved_utc":stamp(),
                    "http_status":r.status_code,"html_sha256":hashlib.sha256(r.content).hexdigest(),
                    "players":players})
        print(f"NBA.com team {team}: HTTP 200, {len(players)} roster-table names",flush=True)
    return out

def reconcile(previous,pages,checked_utc=None):
    fail(previous.get("schema")=="nba-moonshot-roster-preflight/v1","Invalid prior audit")
    fail(previous.get("season")==2027,"Wrong prior season")
    fail(set(previous.get("opening_night_teams",[]))==set(TEAMS),"Wrong team scope")
    prev=previous.get("players",[])
    fail(len(prev)>=100,"Incomplete prior roster reference")
    pid_lookup=defaultdict(list)
    name_lookup=defaultdict(list)
    for p in prev:
        team,name=p.get("team"),str(p.get("player",""))
        fail(team in TEAMS,"Prior row for unexpected team")
        pid=p.get("observed_nba_player_id") or p.get("seed_nba_player_id")
        if pid: pid_lookup[str(pid)].append(p)
        name_lookup[(team,norm(name))].append(p)
    all_official=[]
    source_meta=[]
    for p in pages:
        team=p.get("team")
        fail(team in TEAMS,"Unexpected NBA.com page team")
        fail(p.get("source_url")==page_url(team),"NBA.com roster source URL mismatch")
        fail(p.get("http_status")==200,"Not a successful NBA.com page fetch")
        members=p.get("players",[])
        fail(10<=len(members)<=25,f"Invalid roster size for {team}")
        official_names=set()
        for member in members:
            name=member.get("player","");idval=member.get("nba_player_id")
            fail(member.get("team")==team and len(norm(name))>2,"Invalid official page player/team")
            fail(norm(name) not in official_names,"Duplicate team/name on NBA.com")
            official_names.add(norm(name))
            if idval is not None:fail(bool(re.fullmatch(r"[0-9]{5,12}",str(idval))),"Invalid linked NBA ID")
            all_official.append({"team":team,"player":name,"nba_player_id":str(idval) if idval else None})
        source_meta.append({k:p[k] for k in ("team","source_url","retrieved_utc","http_status","html_sha256")})
    fail(len(pages)==len(TEAMS) and len({p["team"] for p in pages})==len(TEAMS),"Missing or duplicate NBA.com team page")
    official_ids=defaultdict(list)
    for p in all_official:
        if p["nba_player_id"]:official_ids[p["nba_player_id"]].append(p)
    duplicate_official={k:v for k,v in official_ids.items() if len(v)>1}
    rows=[]
    status=Counter()
    matched_prev=set()
    for p in all_official:
        t,name,pid=p["team"],p["player"],p["nba_player_id"]
        exact=name_lookup.get((t,norm(name)),[])
        ids=pid_lookup.get(pid,[]) if pid else []
        corresponding=[q for q in ids if q["team"]==t]
        old=exact[0] if len(exact)==1 else (corresponding[0] if len(corresponding)==1 else None)
        old_pid=(str(old.get("observed_nba_player_id") or old.get("seed_nba_player_id"))
                 if old and (old.get("observed_nba_player_id") or old.get("seed_nba_player_id")) else None)
        resolved=pid or old_pid
        note=[]
        if len(exact)>1 or len(corresponding)>1 or (pid and pid in duplicate_official):
            state="AMBIGUOUS_OR_DUPLICATE_NBA_ID"
        elif old:
            if pid and old_pid and pid!=old_pid:
                state="ID_CONFLICT_REVIEW"
            elif pid and (not old_pid or pid==old_pid):
                state="NBA_PAGE_ID_MATCHED"
            elif not pid and old_pid:
                state="NBA_PAGE_NAME_MATCH_ID_FROM_PRIOR"
            else:
                state="NBA_PAGE_LISTED_ID_UNRESOLVED"
            matched_prev.add((old["team"],norm(old["player"])))
        elif pid and ids and not corresponding:
            state="LISTED_ON_DIFFERENT_NBA_TEAM"
        elif pid:
            state="NEW_NBA_PAGE_PLAYER_ID"
        else:
            state="NEW_NBA_PAGE_PLAYER_NO_ID"
        if state in ("ID_CONFLICT_REVIEW","AMBIGUOUS_OR_DUPLICATE_NBA_ID"):
            note.append("Blocked until NBA ID manually resolved with authoritative evidence")
        status[state]+=1
        rows.append({"team":t,"player":name,"nba_player_id":resolved,"page_link_nba_id":pid,
                     "prior_nba_id":old_pid,"status":state,"source_url":page_url(t),
                     "note":"; ".join(note)})
    removed=[]
    for p in prev:
        if (p["team"],norm(p["player"])) not in matched_prev:
            candidate=p.get("observed_nba_player_id") or p.get("seed_nba_player_id")
            other=official_ids.get(str(candidate),[]) if candidate else []
            different=[v["team"] for v in other if v["team"]!=p["team"]]
            state="POSSIBLE_TEAM_CHANGE" if different else "MISSING_FROM_NBA_COM_PAGE"
            status[state]+=1
            removed.append({"previous_team":p["team"],"player":p["player"],"previous_nba_id":candidate,
                            "status":state,"new_teams_on_pages":different,
                            "note":"Page absence does NOT prove waiver, injury, or ineligibility"})
    issues=[]
    for x in ["ID_CONFLICT_REVIEW","AMBIGUOUS_OR_DUPLICATE_NBA_ID","NEW_NBA_PAGE_PLAYER_NO_ID",
              "NBA_PAGE_LISTED_ID_UNRESOLVED","LISTED_ON_DIFFERENT_NBA_TEAM"]:
        if status[x]: issues.append(f"{status[x]} {x}")
    if duplicate_official:issues.append("Duplicate linked NBA ID across official roster pages")
    return {"schema":SCHEMA,"season":2027,"generated_utc":checked_utc or stamp(),
            "scope":"six opening-night teams, October 20 2026",
            "source_kind":SOURCE_KIND,
            "roster_snapshot_verified":"NBA_COM_TEAM_PAGE_AS_FETCHED",
            "opening_night_final_roster_certified":False,
            "game_day_availability_certified":False,"paid_sgo_allowed":False,
            "note":"Team pages change. This is a current NBA.com roster PAGE comparison, not the league's final roster release or a game-day status check.",
            "prior_preseason_audit_utc":previous.get("checked_utc"),
            "sources":sorted(source_meta,key=lambda x:x["team"]),
            "counts":{"nba_page_players":len(rows),"prior_preseason_entries":len(prev),
                      "no_longer_on_same_team_page":len(removed),
                      "status_counts":dict(sorted((k,v) for k,v in status.items() if v))},
            "issues":issues,
            "players":sorted(rows,key=lambda x:(x["team"],norm(x["player"]))),
            "prior_players_not_matched":sorted(removed,key=lambda x:(x["previous_team"],norm(x["player"])))}

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--preflight",default="published/roster_preflight_2027.json")
    a.add_argument("--out",default="published/official_roster_page_comparison_2027.json")
    opts=a.parse_args()
    previous=json.loads(pathlib.Path(opts.preflight).read_text(encoding="utf-8"))
    pages=fetch_official_pages()
    output=reconcile(previous,pages)
    target=pathlib.Path(opts.out)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("NBA.COM PAGE COMPARISON: "+str(output["counts"]),flush=True)
    print("ISSUES: "+str(output["issues"]),flush=True)
    print("FINAL OFFICIAL OPENING-NIGHT ROSTER: NOT CERTIFIED",flush=True)
    print("PAID SGO: BLOCKED",flush=True)

if __name__=="__main__":
    main()
