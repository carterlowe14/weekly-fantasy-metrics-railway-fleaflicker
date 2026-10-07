# Fantasy Football Metrics Weekly Report (Railway Edition)

A high-performance, automated reporting system for Fantasy Football leagues. This repository is a streamlined deployment bundle optimized for Railway.app.

## Overview

This application automates the retrieval of league data from platforms (primarily Fleaflicker), calculates advanced metrics and rankings, generates a professionally formatted PDF report, and distributes it via integrations like Discord.

### Key Features
- **Automated Data Retrieval**: Integrates with multiple fantasy platforms.
- **Advanced Analytics**: Calculates coaching efficiency, power rankings, and luck metrics.
- **PDF Generation**: Produces high-quality reports with charts and team pages.
- **Discord Integration**: Automatically posts the final report to your league's Discord server.
- **Trigger-Based Execution**: Can be run as a one-shot job or a long-lived service triggered via API.

## Deployment on Railway

### 1. Configuration
Set the following environment variables in your Railway project settings:

| Variable | Example Value | Description |
| :--- | :--- | :--- |
| `PLATFORM` | `fleaflicker` | The fantasy football platform used by your league. |
| `LEAGUE_ID` | `123456` | Your league's unique ID. |
| `SEASON` | `2026` | NFL season year. Defaults to the current calendar year. |
| `WEEK_FOR_REPORT` | `default` | Use `default` for the last completed week, or a week number. |
| `CURRENT_NFL_WEEK` | `2` | Optional. Pins the current NFL week instead of asking Sleeper. |
| `DISCORD_WEBHOOK_ID` | `your-webhook-id` | Discord webhook ID for report delivery. |
| `DISCORD_ROLE_ID` | `123456789` | Role ID to ping when the report is posted. |
| `DISCORD_POST_BOOL` | `true` | Enable/disable Discord delivery. |
| `DISCORD_POST_OR_FILE` | `file` | Use `file` to upload PDF or `post` for a link. |
| `SPOTRAC_API_KEY` | `your-parse-api-key` | Parse API key used only when the public Spotrac fines page is unavailable. Store the real value in Railway variables; never commit it. |
| `SPOTRAC_MONTHLY_CREDIT_LIMIT` | `300` | Maximum Parse credits this app will reserve per UTC month (search costs 1; player fines costs 3). |
| `USE_DEFAULT` | `1` | Set to `1` for fully unattended execution. |
| `CHECK_FOR_UPDATES` | `false` | Disable update checks in production. |
| `TRIGGER_SECRET` | `a-long-random-string` | Shared secret required by `POST /trigger` as `X-Trigger-Secret`. |

#### High Roller data

High Roller first scrapes Spotrac's public season fines page at no Parse-credit cost. If Spotrac blocks the request or the table markup cannot be parsed, it falls back to the Parse.bot API. Create a Parse API key under **Settings → API Keys** and set `SPOTRAC_API_KEY` in Railway; keep the key out of source control. `SPOTRAC_MONTHLY_CREDIT_LIMIT` defaults to 300, and usage is tracked in the league data directory. This local limit only accounts for calls made by this app, not other projects using the same Parse account.

The report looks up fines only for players in the selected report week's active lineup; bench and taxi players are excluded. The public scrape supplies all visible fined players in one request. If Parse fallback is needed, player IDs are cached and per-player fine summaries are reused for 30 days. Fallback calls are limited to active players and stop before exceeding the configured monthly credit cap.

The report includes league-wide High Roller Rankings and a per-team **Paid the Piper** list. If the API returns aggregate fine totals without individual violation details, the total is still shown and unavailable worst-fine details appear as `N/A`.

### 2. Execution Modes

#### A. Long-Lived Trigger Service
If you want the app to stay online and be triggered by external tools (like CarlBot):
**Start Command:**
```bash
python main.py --serve
```
- `GET /health`: Health check for Railway.
- `POST /trigger`: Triggers a report generation run. Send header `X-Trigger-Secret` when `TRIGGER_SECRET` is set.

#### B. One-Shot Scheduled Job
If you want Railway to run the report on a schedule (e.g., every Tuesday):
**Start Command:**
```bash
bash RAILWAY/start-report.sh
```

## Project Structure

- `ffmwr/`: Core application logic.
  - `calculate/`: Metric and probability calculations.
  - `dao/`: Data Access Objects for platform APIs.
  - `report/`: PDF generation and data assembly.
  - `utilities/`: App settings and logging.
- `RAILWAY/`: Deployment scripts and configuration.
- `resources/`: Fonts, images, and report templates.
- `main.py`: Application entry point.
- `requirements.txt`: Python dependencies.
- `Dockerfile`: Build configuration for Railway.
