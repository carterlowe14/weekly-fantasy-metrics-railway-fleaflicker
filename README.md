# Railway deployment

This folder is the compact deployment bundle for the scheduled weekly report.

It contains only the runtime files needed to run the app on Railway:

- `Dockerfile` — container build for the app
- `railway.json` — Railway deployment config
- `main.py` — app entrypoint
- `pyproject.toml` — Python dependencies
- `ffmwr/` — application code
- `resources/` — fonts, images, and report resources
- `.env.example` — template for Railway environment variables

## Schedule

Set the Railway schedule to run every Tuesday and execute:

```bash
python main.py --use-default
```

This is the default production command and should be used instead of interactive prompts.

## Required Railway environment variables

At minimum, set these in Railway project variables:

- `PLATFORM=fleaflicker`
- `LEAGUE_ID=123456`
- `SEASON=2026`
- `CURRENT_NFL_WEEK=1`
- `DISCORD_WEBHOOK_ID=your-discord-webhook-id`

Optional but commonly used:

- `DISCORD_POST_BOOL=true`
- `DISCORD_POST_OR_FILE=file`
- `CHECK_FOR_UPDATES=false`
- `USE_DEFAULT=1`

If you are using a different platform, set `PLATFORM` to one of the supported values from the app config (`yahoo`, `espn`, `sleeper`, `fleaflicker`, `cbs`).

## Example local shell setup

```bash
export PLATFORM=fleaflicker
export LEAGUE_ID=123456
export SEASON=2026
export CURRENT_NFL_WEEK=1
export DISCORD_WEBHOOK_ID=your-discord-webhook-id
export DISCORD_POST_BOOL=true
export DISCORD_POST_OR_FILE=file

python main.py --use-default
```

## Notes

- The app still supports a local `.env` file for development, but production jobs should use Railway environment variables.
- The scheduled job is designed to be unattended and non-interactive.
- This folder is intentionally lean and self-contained so it can be uploaded to GitHub as a deployment bundle.
