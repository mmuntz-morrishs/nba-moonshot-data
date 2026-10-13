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