# Railway deployment

This is the compact deployment bundle for the weekly fantasy football report app.

## What it does

- reads your Fleaflicker league
- generates the weekly PDF report
- posts it to Discord automatically
- runs unattended on Railway

## Required Railway environment variables

Set these in the Railway project variables:

- `PLATFORM=fleaflicker`
- `LEAGUE_ID=123456`
- `DISCORD_WEBHOOK_ID=your-discord-webhook-id`
- `DISCORD_ROLE_ID=123456789012345678`
- `DISCORD_CHANNEL_NOTIFY_BOOL=true`
- `DISCORD_POST_BOOL=true`
- `DISCORD_POST_OR_FILE=file`
- `CHECK_FOR_UPDATES=false`
- `USE_DEFAULT=1`

Notes:
- `SEASON` is not required. The app automatically uses the current calendar year.
- `DISCORD_ROLE_ID` is the Discord role ID to ping each run.
- `USE_DEFAULT=1` keeps the job fully unattended.
- The app automatically fetches the live NFL week from Sleeper instead of relying on a manual week value.

## Railway deploy command

```bash
python main.py --use-default
```

## Example local shell setup

```bash
export PLATFORM=fleaflicker
export LEAGUE_ID=123456
export DISCORD_WEBHOOK_ID=your-discord-webhook-id
export DISCORD_ROLE_ID=123456789012345678
export DISCORD_CHANNEL_NOTIFY_BOOL=true
export DISCORD_POST_BOOL=true
export DISCORD_POST_OR_FILE=file
export CHECK_FOR_UPDATES=false
export USE_DEFAULT=1

python main.py --use-default
```

## Schedule

Run the job weekly on Railway. Tuesday is the normal choice.
