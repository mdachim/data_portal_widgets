# Moldova refugee response: operational picture

Single-page dashboard for the left pane of the UNHCR Operational Data Portal
page for Moldova. It is embedded by iframe from GitHub Pages and reads one file,
`data/operational.json`.

## How the data gets there

```
population_movement/pop_trends.json ─┐
population_movement/tp_data.json ────┤
rrp_2026/data.json ──────────────────┼─►  scripts/build_operational.py  ─►  data/operational.json  ─►  index.html
rrp_2026/indicator_config.json ──────┤                                      (committed by the Action)
rrp_2026/targets_2026.json ──────────┤
data/manual.json (edited by hand) ───┘
```

`.github/workflows/sync-data.yml` downloads the five source files, runs the
build script and commits `data/operational.json` only when its content changed.
It runs every 6 hours, on the **Run workflow** button, whenever `manual.json`
or the script changes, and on a `repository_dispatch` event of type
`source-updated`.

If a source file is missing or malformed, the script exits with an error and the
last good `operational.json` stays in place.

## What comes from where

| On the page | Source |
|---|---|
| Refugees from Ukraine in Moldova, "Who the refugees are" | `pop_trends.json`, latest month, `stay_ukraine` (arrived directly from Ukraine) |
| Border crossings | `pop_trends.json`, latest month, arrivals + departures |
| Temporary protection beneficiaries | `tp_data.json`, newest snapshot (cumulative, plus change in the latest interval) |
| Monthly arrivals & departures chart | `pop_trends.json`, all months |
| Partners' achievements | `rrp_2026/data.json` against `targets_2026.json`, rolled up per `indicator_config.json` |
| RRP 2026 funded, key resources, dashboard tiles | `data/manual.json` |

The achievements calculation mirrors `rrp_2026/index.html` (indicator
methodologies Sum / Max Raion / Max Countrywide, sector progress = achieved ÷
target over indicators that have a target). If that dashboard's logic changes,
update `build_achievements()` to match.

## Editing by hand

`data/manual.json` holds:

- `rrp_funded.pct`: the RRP funding percentage (27 for now).
- `resources`: the four featured documents.
- `dashboards`: the two "More interactive dashboards" tiles.

Commit a change to that file and the workflow rebuilds `operational.json`.

## Set-up

1. Create the repository and push these files.
2. Settings → Pages → deploy from branch `main`, root folder.
3. Settings → Actions → General → Workflow permissions → **Read and write**.
4. Run the workflow once from the Actions tab, then check that Pages redeploys.
5. Embed `https://<user>.github.io/<repo>/` in the left pane. The page scrolls
   inside its own frame when embedded, so a fixed iframe height is fine.

Optional instant refresh: add a step to a source repo's workflow that calls the
`repository_dispatch` API on this repo with `{"event_type":"source-updated"}`
(needs a token with access to this repo).

## Local preview and rebuild

Double-click `index.html` to preview it from disk. Browsers block `fetch()` on
`file://` addresses, so in that case the page reads `data/operational.js`, a
copy of `operational.json` that the build script writes alongside it. Hosted on
GitHub Pages it reads the JSON.

To rebuild the data yourself:

```
mkdir .sources   # put the five source JSON files in it
python3 scripts/build_operational.py --sources .sources --manual data/manual.json --out data/operational.json
```

Chart.js 4.5.0 is vendored in `vendor/` (MIT licence alongside), so the page has
no script dependency on a CDN. Only the Lato font loads from Google Fonts.
