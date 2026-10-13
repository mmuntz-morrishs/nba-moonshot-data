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
