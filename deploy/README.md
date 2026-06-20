# Automated daily refresh (macOS)

Keeps the live app current by rebuilding and republishing whenever the season
has new games. It runs on a home machine on purpose: `stats.nba.com` blocks
datacenter/cloud IPs (a GitHub Actions probe timed out on the first call), so a
residential IP is required for ingest. The job is gated by a cheap freshness
check, so it does real work only when new games exist - frequent in-season,
idle all summer, with no calendar logic to maintain.

## What runs

`scripts/refresh.sh`, once a day:

1. `src/check_for_new_games.py` - one light index call; exits 0 if the current
   season has games we lack, 1 otherwise.
2. on new games: `just full` (incremental ingest -> rebuild -> retrain -> export).
3. commits the refreshed serving artifacts + model and pushes to `main`, which
   triggers a Streamlit Community Cloud redeploy.

Try it by hand first: `just refresh`.

## One-time setup

### 1. Allow the push to `main`

The `main` branch ruleset requires pull requests, so a direct push from the job
is rejected. Add a bypass for the account whose credentials the job uses:

> Settings -> Rules -> Rulesets -> (the `main` ruleset) -> Bypass list ->
> add your account (or "Repository admin") -> Save.

Code still goes through PRs; only this automated data push uses the bypass.
Verify credentials are non-interactive (the job cannot answer a password prompt):
`git push` should already work from a terminal via the macOS keychain helper.

### 2. Install the LaunchAgent

```bash
# Edit the paths in the plist if the repo is not at the default location.
cp deploy/com.knicks-win-probability.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.knicks-win-probability.refresh.plist

# Run it once now to confirm it works end to end:
launchctl start com.knicks-win-probability.refresh
tail -f refresh.log
```

To change the time, edit `StartCalendarInterval` in the plist, then
`launchctl unload` and `load` it again. To stop the schedule entirely:

```bash
launchctl unload ~/Library/LaunchAgents/com.knicks-win-probability.refresh.plist
```

## Notes

- The job only ever publishes from a clean `main` checkout; it aborts on any
  other branch so it can never commit work in progress. Running it from your
  primary working copy is fine as long as you keep that copy on `main`.
- Output is appended to `refresh.log` in the repo root (gitignored).
