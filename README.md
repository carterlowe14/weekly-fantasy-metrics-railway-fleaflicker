# 🏈 Fantasy Football Metrics Weekly Report (Railway Edition)

A high-performance, automated reporting system for Fantasy Football leagues. This repository is a streamlined deployment bundle optimized for Railway.app.

## 🚀 Overview

This application automates the retrieval of league data from platforms (primarily Fleaflicker), calculates advanced metrics and rankings, generates a professionally formatted PDF report, and distributes it via integrations like Discord.

### Key Features
- **Automated Data Retrieval**: Integrates with multiple fantasy platforms.
- **Advanced Analytics**: Calculates coaching efficiency, power rankings, and luck metrics.
- **PDF Generation**: Produces high-quality reports with charts and team pages.
- **Discord Integration**: Automatically posts the final report to your league's Discord server.
- **Trigger-Based Execution**: Can be run as a one-shot job or a long-lived service triggered via API.

## 🛠️ Deployment on Railway

### 1. Configuration
Set the following environment variables in your Railway project settings:

| Variable | Example Value | Description |
| :--- | :--- | :--- |
| `PLATFORM` | `fleaflicker` | The fantasy football platform used by your league. |
| `LEAGUE_ID` | `123456` | Your league's unique ID. |
| `DISCORD_WEBHOOK_ID` | `your-webhook-id` | Discord webhook ID for report delivery. |
| `DISCORD_ROLE_ID` | `123456789` | Role ID to ping when the report is posted. |
| `DISCORD_POST_BOOL` | `true` | Enable/disable Discord delivery. |
| `DISCORD_POST_OR_FILE` | `file` | Use `file` to upload PDF or `post` for a link. |
| `USE_DEFAULT` | `1` | Set to `1` for fully unattended execution. |
| `CHECK_FOR_UPDATES` | `false` | Disable update checks in production. |

### 2. Execution Modes

#### A. Long-Lived Trigger Service
If you want the app to stay online and be triggered by external tools (like CarlBot):
**Start Command:**
```bash
python main.py --serve
```
- `GET /health`: Health check for Railway.
- `POST /trigger`: Triggers a report generation run.

#### B. One-Shot Scheduled Job
If you want Railway to run the report on a schedule (e.g., every Tuesday):
**Start Command:**
```bash
bash RAILWAY/start-report.sh
```

## 📂 Project Structure

- `ffmwr/`: Core application logic.
  - `calculate/`: Metric and probability calculations.
  - `dao/`: Data Access Objects for platform APIs.
  - `report/`: PDF generation and data assembly.
  - `utilities/`: App settings and logging.
- `RAILWAY/`: Deployment scripts and configuration.
- `resources/`: Fonts, images, and report templates.
- `main.py`: Application entry point.
- `requirements.txt`: Python dependencies.
- `nixpacks.toml`: Build configuration for Railway.
