#!/usr/bin/env python3
"""Manual-only NBA DuckDB -> Moonshot JSON exporter. No Sheet writes or SGO."""
import argparse, datetime as dt, hashlib, json, pathlib, re

CATALOG="https://basketball-data.billmill.org/nba/nba.duckdb"
SCHEMA="nba-moonshot-json-bridge/v1"
GROUND={
 ("0022500001","1630598"):("OKC",5,2),
 ("0022500001","1642349"):("OKC",6,3),
 ("0022500001","1630578"):("HOU",8,5),
 ("0022500002","201939"):("GSW",9,3),
 ("0022500002","1627741"):("GSW",10,5),
 ("0022500002","1629029"):("LAL",10,2),
}

def check(ok,msg):
 if not ok: raise ValueError(msg)

def normalize(games,records,season,roster=None,source=CATALOG):
 check(season in (2026,2027),"Unsupported season")
 lookup={}
 for g in games:
  gid=str(g["game_id"]); day=str(g["game_date"])
  check(bool(re.fullmatch(r"002\d{7}",gid)) and gid[3:5]==str(season-2001),"Bad season/game ID")
  check(g["game_type"]=="regular_season","Preseason or other game type")
  check(bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}",day)),"Invalid date")
  home,away=str(g["home_team"]),str(g["away_team"])
  check(bool(re.fullmatch(r"[A-Z]{2,3}",home) and re.fullmatch(r"[A-Z]{2,3}",away)) and home!=away,"Invalid teams")
  check(gid not in lookup,"Duplicate game")
  lookup[gid]={"game_id":gid,"game_date":day,"home_team":home,"away_team":away,"game_type":"regular_season"}
 out=[]; seen=set()
 for src in records:
  gid,pid=str(src["game_id"]),str(src["player_id"])
  check(gid in lookup,"Unknown / non-regular game")
  check(bool(re.fullmatch(r"\d{1,12}",pid)),"Bad NBA player ID")
  check((gid,pid) not in seen,"Duplicate game/player")
  seen.add((gid,pid))
  g=lookup[gid]; team,opp=str(src["team"]),str(src["opponent"])
  check(str(src["game_date"])==g["game_date"],"Game date mismatch")
  check({team,opp}=={g["home_team"],g["away_team"]} and team!=opp,"Team/opponent mismatch")
  a,m=src["three_pa"],src["three_pm"]
  check(type(a)==int and type(m)==int and 0<=m<=a<=40,"Invalid three-point counts")
  minutes=float(src["minutes"])
  check(0<=minutes<=65,"Invalid minutes")
  name=str(src["player"]).strip()
  check(2<=len(name)<=80,"Invalid name")
  out.append({"game_date":g["game_date"],"game_id":gid,"player_id":pid,"player":name,"team":team,
              "opponent":opp,"minutes":round(minutes,2),"three_pa":a,"three_pm":m})
 out.sort(key=lambda r:(r["game_date"],r["game_id"],r["player_id"]))
 roster=roster or []; normalized=[]; roster_seen=set()
 for r in roster:
  pid,team=str(r["player_id"]),str(r["team"])
  check(bool(re.fullmatch(r"\d{1,12}",pid) and re.fullmatch(r"[A-Z]{2,3}",team)),"Bad roster entry")
  check((pid,team) not in roster_seen,"Duplicate roster entry")
  roster_seen.add((pid,team))
  normalized.append({"nba_player_id":pid,"player":str(r["player"]).strip(),"team":team,
                     "verification":"RECENT_GAME_ASSOCIATION_ONLY"})
 normalized.sort(key=lambda r:(r["team"],r["nba_player_id"]))
 serial="\n".join("\t".join(str(r[k]) for k in
  ("game_id","player_id","team","opponent","three_pa","three_pm")) for r in out)
 demo=(season==2026 or not out)
 return {"schema":SCHEMA,"season":season,"season_label":f"{season-1}-{str(season)[-2:]}",
         "exported_at_utc":dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "source":source,"demo_only":demo,
         "source_verification":"HISTORICAL_REFERENCE" if season==2026 else "REMOTE_UNCERTIFIED",
         "roster_status":"RECENT_GAME_ASSOCIATIONS_NOT_GAME_DAY_CONFIRMED",
         "counts":{"games":len(lookup),"player_games":len(out),"roster":len(normalized)},
         "hash_algorithm":"sha256-lf-tab-keys-v1",
         "records_sha256":hashlib.sha256(serial.encode("utf-8")).hexdigest(),
         "games":sorted(lookup.values(),key=lambda r:(r["game_date"],r["game_id"])),
         "roster":normalized,"player_game_logs":out}

def remote(season,limited=False):
 import duckdb
 c=duckdb.connect()
 c.execute(f"ATTACH '{CATALOG}' AS nba (READ_ONLY)")
 extra=" AND g.game_id IN ('0022500001','0022500002')" if limited else ""
 games=c.execute("""
   SELECT g.game_id,cast(g.game_date as varchar),h.nba_abbrev,a.nba_abbrev,g.game_type
   FROM nba.games g
   JOIN nba.team_seasons h ON g.season=h.season AND g.home_team_id=h.team_id
   JOIN nba.team_seasons a ON g.season=a.season AND g.away_team_id=a.team_id
   WHERE g.season=? AND g.game_type='regular_season' AND g.game_id LIKE '002%'
   """+extra+" ORDER BY 2,1",[season]).fetchall()
 rows=c.execute("""
   SELECT cast(l.game_date as varchar),l.game_id,l.player_id,p.name,
          t.nba_abbrev,o.nba_abbrev,l.min,l.fg3a,l.fg3m
   FROM nba.player_game_logs l
   JOIN nba.games g ON g.season=l.season AND g.game_id=l.game_id
   JOIN nba.player_seasons p ON p.season=l.season AND p.player_id=l.player_id
   JOIN nba.team_seasons t ON t.season=l.season AND t.team_id=l.team_id
   JOIN nba.team_seasons o ON o.season=l.season AND o.team_id=l.opp_team_id
   WHERE l.season=? AND g.game_type='regular_season' AND l.game_id LIKE '002%'
   """+extra+" ORDER BY 1,2,3",[season]).fetchall()
 roster=[]
 if season==2027:
  roster_rows=c.execute("""
    WITH r AS (
      SELECT l.player_id,p.name,t.nba_abbrev,
        row_number() OVER (PARTITION BY l.player_id ORDER BY l.game_date DESC,l.game_id DESC) n
      FROM nba.player_game_logs l
      JOIN nba.player_seasons p ON p.season=l.season AND p.player_id=l.player_id
      JOIN nba.team_seasons t ON t.season=l.season AND t.team_id=l.team_id
      WHERE l.season=? AND t.is_nba AND l.player_id IS NOT NULL
    ) SELECT player_id,name,nba_abbrev FROM r WHERE n=1
  """,[season]).fetchall()
  roster=[{"player_id":a,"player":b,"team":t} for a,b,t in roster_rows if b]
 gs=[{"game_id":a,"game_date":b,"home_team":c,"away_team":d,"game_type":e} for a,b,c,d,e in games]
 ps=[{"game_date":a,"game_id":b,"player_id":c,"player":d,"team":e,"opponent":f,
      "minutes":g,"three_pa":h,"three_pm":i} for a,b,c,d,e,f,g,h,i in rows]
 return normalize(gs,ps,season,roster)

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--mode",choices=["historical-reference","current-season"],required=True)
 p.add_argument("--out",required=True)
 args=p.parse_args()
 season=2026 if args.mode=="historical-reference" else 2027
 out=remote(season,limited=(season==2026))
 if season==2026:
  index={(r["game_id"],r["player_id"]):r for r in out["player_game_logs"]}
  for key,(team,a,m) in GROUND.items():
   check(key in index and (index[key]["team"],index[key]["three_pa"],index[key]["three_pm"])==(team,a,m),
         f"Historical remote reference mismatch: {key}")
  check(out["counts"]["games"]==2,"Historical source not exactly two verified games")
  print("REMOTE HISTORICAL DATA VERIFIED: 6/6 real NBA IDs, teams, and 3PA/3PM")
 else:
  check(out["counts"]["games"] > 0 and out["counts"]["player_games"]>0,"NO_COMPLETED_REGULAR_SEASON_DATA: not publishing live feed")
  print("CURRENT-SEASON SCHEMA VERIFIED (roster status remains provisional)")
 target=pathlib.Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(f"OUTPUT: {target} games={out['counts']['games']} rows={out['counts']['player_games']} recent_id_teams={out['counts']['roster']}")

if __name__=="__main__":main()
