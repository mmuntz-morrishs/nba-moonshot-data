# NBA Moonshot — Public JSON bridge

Independent **paper-only** experiment; not connected to NBAPropSignal V2.

## Published historical example

[View `published/example_historical_bridge.json`](published/example_historical_bridge.json)

- Schema: `nba-moonshot-json-bridge/v1`
- Source: public 2025–26 archived NBA player box scores
- Games: 2; player-game records: 10
- Includes genuine NBA IDs, teams, three-point attempts (`three_pa`) and makes (`three_pm`)
- Flag: **`demo_only: true`** — this is not a current-season feed and must never qualify a paid odds board.

## Verify from Google Apps Script

Use the `ms09RunReadOnlyValidation` function already installed in the NBA Moonshot bound Apps Script project. In **Project Settings → Script Properties**, set:

`MS09_BRIDGE_URL` = `https://raw.githubusercontent.com/mmuntz-morrishs/nba-moonshot-data/main/published/example_historical_bridge.json`

Then run `ms09RunReadOnlyValidation`. It performs a read-only check of the original historical archive and this published JSON, validating the schema, SHA-256 player-game row digest, player IDs, dates, game types, team matches, and exact shooting statistics. **Zero SGO requests, zero Sheet writes, zero retries.**

### Current status

- GitHub publication and repository read-back: **PASS**
- Apps Script fetch of GitHub-hosted export: **PENDING USER TEST**
- Current 2026–27 regular-season export: **NOT IMPLEMENTED/NOT CERTIFIED**
- Game-day rosters: **NOT CERTIFIED**
- Paid SGO board: **BLOCKED**

The next step after historical Apps Script validation is to publish and test a separately generated 2026–27 feed from a source verified accessible to the producer. No autonomous/scheduled jobs should be enabled.

## Current-season data test — manual action

Source code: [`export_bridge.py`](export_bridge.py). Offline tests: [`test_export.py`](test_export.py).
Workflow: [**Moonshot - Validate and Export NBA Data (manual only)**](.github/workflows/validate-and-export.yml).

**How to run:** Open the repository's **Actions** tab, choose **Moonshot - Validate and Export NBA Data (manual only)**, click **Run workflow**, choose branch `main`, and confirm.

This manually triggered workflow, without cron, will:

1. Run nine free offline tests using the certified historical JSON.
2. Ask the public DuckDB catalog for **two October 21, 2025 games**, verify six ground-truth NBA IDs/teams/3PA/3PM.
3. Attempt the 2026–27 regular-season dataset.
4. **Fail closed** if any source, schema, reference or count check fails.
5. If **no completed 2026–27 regular-season game data exists**, report **NOT READY**, do not publish the current-season file, and use no SGO requests.
6. Only after complete regular-season data and preceding checks exist, publish `published/current_season_bridge.json`.

The 2026–27 exporter has **not yet passed a live DuckDB query**. A successful historical bridge check **does not** certify future results. Even when current-season data becomes available, recent team-game association is not equivalent to an official active game-day roster.

Do **not** change the `MS09_BRIDGE_URL` script property away from the historical example while validating the producer. Do not run the paid board until a real 2026–27 JSON fetch passes Apps Script and a separately confirmed roster check is complete. `NBAPropSignal V2` and the frozen Moonshot model remain untouched.

## 2026-27 roster / NBA player-ID preflight — October 13

This is **separate** from the regular-season shooting-log export because preseason game logs exist before the regular-season tipoff.

- [Manual roster check workflow](.github/workflows/roster-id-preflight.yml)
- [Read-only DuckDB query and identity reconciliation](roster_preflight.py)
- [14 offline identity/conflict safety tests](test_roster_preflight.py)
- [October 13 provisional six-team seed](reference/opening_six_roster_seed_2026-10-13.json)

Click **Actions → Moonshot - Verify 2026-27 NBA IDs and Preseason Rosters (manual only) → Run workflow → main**.

The script uses NBA ID and team records from the new season's NBA preseason/regular game logs (including transfers to the other 24 NBA teams), then reconciles the six teams scheduled for Oct 20 (BOS/DET/PHI/NYK/OKC/SAS) against the Oct 13 preseason snapshot: 125 names, 93 historical NBA IDs, 32 missing. It flags missing current-game participation, exact-name recovered IDs, potential identity conflicts, duplicate IDs, and team transfers.

The resulting [provisional roster audit](published/roster_preflight_2027.json) will only be created if 2026-27 observed game data is actually returned and checks pass. It includes evidence game dates and IDs plus coverage and issues. Any incomplete team coverage stays conspicuous; **no team or player receives active game-day certification**.

The Oct 19 official roster cutoff remains a separate requirement. An NBA.com preseason listing or a preseason game does **not** prove eligibility/availability on Oct 20. A "successful" GitHub Actions run still does not permit SGO odds requests. No Sheet writes, no SGO requests, no scheduled updates, no NBAPropSignal V2 crossover. The existing historical-only Apps Script property \`MS09_BRIDGE_URL\` stays unchanged.

## NBA.com official team PAGE reconciliation (manual only)

**Before October 19:** NBA.com public team pages may still list preseason players, so page comparison is a provisional data-source test, **not final opening-night certification**.

Workflow: [Moonshot - Reconcile Six NBA.com Team Rosters](.github/workflows/official-roster-reconcile.yml). Run it manually from Actions > this workflow > Run workflow > main.

The manual job runs 14 offline parser/identity tests, then makes one HTTP GET to each of six public NBA.com team pages: Boston, Detroit, Philadelphia, New York, Oklahoma City, San Antonio. No retries, scheduled triggers, NBAPropSignal V2 access, SGO requests, or Google Sheet writes. All six pages must return HTTP 200 with exactly one plausible roster table of 10-25 players.

On success, compares rosters against [the 2026-27 NBA-ID preflight](published/roster_preflight_2027.json), and publishes [a separate NBA.com page comparison](published/official_roster_page_comparison_2027.json) with sources, fetch timestamps, page SHA-256s, IDs, new names, missing names, and conflicts. A failed source produces no published comparison.

**Permanent safety flags:** opening_night_final_roster_certified=false; game_day_availability_certified=false; paid_sgo_allowed=false. The NBA's official final opening-day roster release and October 20 game-day availability remain separate checks. Page absence does not prove waiver, trade, injury, or ineligibility.

If GitHub Actions receives HTTP 403 or the roster page format changes, treat it as a blocked source. Once published, an NBA-issued final roster document can serve as the separate authoritative release; never use preseason box-score participation as proof of final roster status.

## NBA.com direct HTTP 403: cached NBA API roster alternative

The manual NBA.com roster-page workflow returned HTTP 403 on GitHub Actions; this is a **source-access failure**, not a rejected identity match. The failed workflow did not publish partial data. Do not retry the blocked NBA.com URL.

**New one-request manual workflow:** [Moonshot - Verify Cached NBA Team Rosters](.github/workflows/cached-nba-roster-reconcile.yml). Open Actions, select it, and click Run workflow for main. It runs [14 offline tests](test_cached_nba_roster_reconcile.py) and then executes [cached_nba_roster_reconcile.py](cached_nba_roster_reconcile.py).

Candidate: the basketball-data project's cached raw NBA `CommonTeamRoster` responses at `https://basketball-data.billmill.org/nba/raw/stats/2027/team_rosters.json.gz`. Its upstream publisher's `pipeline/stats.py` stores the `fetched` timestamp plus a map of team IDs to raw NBA roster API responses. The URL **has not yet been verified reachable from GitHub Actions**. A failure must halt without publication.

The new check demands a fresh timestamp (at most 72h), exactly all 30 NBA team identifiers, NBA `PLAYER_ID` and `PLAYER` headers, plausible roster row counts, no duplicate IDs on a single team, and comparison to our six-team 2026-27 ID audit. It flags conflicting/duplicated IDs, roster additions, missing names, and possible team moves. Team-page absence or roster absence does not prove release, injury, or ineligibility.

On passing all checks, GitHub publishes `published/cached_nba_roster_reconciliation_2027.json` with source timestamp, binary SHA-256 provenance, detailed changes, and the **permanent** flags `official_oct19_final_rosters_certified=false`, `oct20_game_day_availability_certified=false`, and `paid_sgo_allowed=false`.

The October 19 official league final roster release and October 20 game-day player availability still require separate checks. Never unlock paid SGO requests on this snapshot alone, and do not change the frozen Moonshot model, Google Sheet, or NBAPropSignal V2.

### October 13 ID anomaly handling (cached NBA API)

The first manual cache run **reached and decompressed** the raw NBA `CommonTeamRoster` snapshot, but stopped at an invalid `PLAYER_ID` in Philadelphia (team ID `1610612755`). This was a **player-level source anomaly**, not an HTTP failure. No report was published and SGO stayed blocked.

The updated `cached_nba_roster_reconcile.py` safely **quarantines** up to three malformed/missing NBA IDs per 30-team roster when at least eight valid IDs remain. A quarantined entry retains the NBA-listed player name, team, source raw ID, and `NBA_API_PLAYER_ID_UNRESOLVED` status, with `nba_player_id=null`. It is never silently assigned the historical ID or counted as verified. Excessive anomalies, duplicate NBA IDs within a team, malformed names, stale snapshots, and missing teams still stop the workflow.

The updated workflow has **18 offline checks** and validates the quarantined counts before publishing the provisional JSON. See [manual workflow](.github/workflows/cached-nba-roster-reconcile.yml). A workflow success only certifies parsing and safe reporting; it never certifies October 19 final rosters or October 20 availability. Paid SGO stays blocked.
