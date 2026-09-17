__author__ = "Wren J. R. (uberfastman)"
__email__ = "uberfastman@uberfastman.dev"

import os
import secrets
import sys
import warnings
from argparse import ArgumentParser, HelpFormatter, Namespace
from datetime import datetime
from pathlib import Path
from typing import Optional

import colorama
import uvicorn
from colorama import Fore, Style
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from ffmwr.integrations.discord import DiscordIntegration
from ffmwr.integrations.drive import GoogleDriveIntegration
from ffmwr.integrations.groupme import GroupMeIntegration
from ffmwr.integrations.slack import SlackIntegration
from ffmwr.report.builder import FantasyFootballReport
from ffmwr.utilities.app import check_github_for_updates
from ffmwr.utilities.logger import get_logger
from ffmwr.utilities.settings import AppSettings, get_app_settings_from_env_file
from ffmwr.utilities.utils import format_platform_display

# Suppress noisy SyntaxWarnings from transitive dependencies
if not sys.warnoptions:
    warnings.filterwarnings("ignore", category=SyntaxWarning)

colorama.init()
logger = get_logger()

app = FastAPI(title="Fantasy Football Metrics Weekly Report Trigger")

TRIGGER_SECRET = os.getenv("TRIGGER_SECRET")
if not TRIGGER_SECRET:
    logger.warning(
        'TRIGGER_SECRET is not set. The "/trigger" endpoint is UNAUTHENTICATED '
        "and can be called by anyone who has the URL. Set TRIGGER_SECRET to lock it down."
    )


# ---------------------------------------------------------------------------
# Security dependency
# ---------------------------------------------------------------------------
def verify_trigger_secret(x_trigger_secret: Optional[str] = Header(default=None)) -> None:
    if not TRIGGER_SECRET:
        return
    if not x_trigger_secret or not secrets.compare_digest(x_trigger_secret, TRIGGER_SECRET):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Trigger-Secret header.")


# ---------------------------------------------------------------------------
# Background cleanup
# ---------------------------------------------------------------------------
def remove_file(path: Path) -> None:
    """Delete the generated PDF after it has been fully served."""
    try:
        if path.exists():
            path.unlink()
            logger.info("Cleaned up temporary report file: %s", path.name)
    except Exception as exc:
        logger.error("Failed to delete temporary file %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Health & trigger endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/trigger")
def trigger_report(
    background_tasks: BackgroundTasks,
    _=Depends(verify_trigger_secret),
) -> FileResponse:
    """
    Always runs with the .env defaults — no per-request configuration accepted.
    Returns the generated PDF and schedules it for deletion after the response.
    """
    root_directory = Path(__file__).parent
    app_settings = get_app_settings_from_env_file(root_directory / ".env")

    args = build_default_args(app_settings)
    args.skip_uploads = False  # force uploads when triggered via HTTP

    try:
        report_pdf = run_report(args, app_settings, root_directory)
    except RuntimeError as exc:
        logger.error("Report generation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during report generation")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}") from exc

    background_tasks.add_task(remove_file, report_pdf)
    return FileResponse(
        path=report_pdf,
        media_type="application/pdf",
        filename=report_pdf.name,
    )


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------
def build_default_args(app_settings: AppSettings) -> Namespace:
    """Create a Namespace that forces the application to use .env defaults."""
    return Namespace(
        fantasy_platform=None,
        league_id=None,
        yahoo_game_id=None,
        year=None,
        start_week=None,
        week=None,
        use_default=True,
        save_data=False,
        refresh_feature_web_data=False,
        playoff_prob_sims=None,
        break_ties=False,
        disqualify_coaching_efficiency=False,
        offline=False,
        skip_uploads=False,
        test=False,
    )


# ---------------------------------------------------------------------------
# Core report runner
# ---------------------------------------------------------------------------
def run_report(args: Namespace, app_settings: AppSettings, root_directory: Path) -> Path:
    if app_settings.check_for_updates:
        check_github_for_updates(args.use_default)

    _log_run_configuration(args, app_settings)

    report = select_league(
        settings=app_settings,
        use_default=args.use_default,
        platform=args.fantasy_platform,
        game_id=args.yahoo_game_id,
        league_id=args.league_id,
        season=args.year,
        start_week=args.start_week,
        week_for_report=args.week,
        break_ties=args.break_ties,
        playoff_prob_sims=args.playoff_prob_sims,
        dq_ce=args.disqualify_coaching_efficiency,
        save_data=args.save_data,
        refresh_feature_web_data=args.refresh_feature_web_data,
        offline=args.offline,
        test=args.test,
    )

    report_pdf = report.create_pdf_report()
    if not report_pdf or not report_pdf.exists():
        raise RuntimeError("PDF report was not created successfully.")

    _handle_uploads(args, app_settings, root_directory, report, report_pdf)
    return report_pdf


def _log_run_configuration(args: Namespace, app_settings: AppSettings) -> None:
    max_key_len = max(len(k) for k in vars(args))
    args_display = "\n".join(
        f"  {k}{'.' * (max_key_len - len(k))}...{v}" for k, v in vars(args).items()
    )
    platform = format_platform_display(
        args.fantasy_platform if args.fantasy_platform else app_settings.platform
    )
    test_label = " TEST" if args.test else ""
    logger.info(
        "\nGenerating%s %s Fantasy Football report on %s with the following arguments:\n\n%s\n",
        test_label,
        platform,
        datetime.now().strftime("%b %d, %Y at %I:%M%p"),
        args_display,
    )


# ---------------------------------------------------------------------------
# Upload / messaging integrations
# ---------------------------------------------------------------------------
def _handle_uploads(
    args: Namespace,
    app_settings: AppSettings,
    root_directory: Path,
    report: FantasyFootballReport,
    report_pdf: Path,
) -> None:
    if args.skip_uploads or args.test:
        logger.info("Skipping all uploads (skip_uploads=%s, test=%s)", args.skip_uploads, args.test)
        return

    google_drive_link: Optional[str] = None

    # Google Drive first — other integrations may reuse its link
    if app_settings.integration_settings.google_drive_upload_bool:
        google_drive_link = _upload_to_google_drive(
            app_settings, root_directory, report.league.week_for_report, report_pdf
        )

    # Messaging platforms
    integrations = [
        (
            "slack",
            app_settings.integration_settings.slack_post_bool,
            SlackIntegration,
            app_settings.integration_settings.slack_post_or_file,
        ),
        (
            "groupme",
            app_settings.integration_settings.groupme_post_bool,
            GroupMeIntegration,
            app_settings.integration_settings.groupme_post_or_file,
        ),
        (
            "discord",
            app_settings.integration_settings.discord_post_bool,
            DiscordIntegration,
            app_settings.integration_settings.discord_post_or_file,
        ),
    ]

    for name, enabled, integration_cls, post_or_file in integrations:
        if not enabled:
            continue
        _post_to_messaging_platform(
            name=name,
            integration_cls=integration_cls,
            post_or_file=post_or_file,
            app_settings=app_settings,
            root_directory=root_directory,
            week=report.league.week_for_report,
            report_pdf=report_pdf,
            google_drive_link=google_drive_link,
        )


def _upload_to_google_drive(
    app_settings: AppSettings,
    root_directory: Path,
    week: int,
    report_pdf: Path,
) -> Optional[str]:
    try:
        integration = GoogleDriveIntegration(app_settings, root_directory, week)
        message = integration.upload_file(report_pdf)

        if message and "http" in message.lower():
            logger.info("Google Drive upload succeeded: %s", message)
            return message

        logger.error("Google Drive upload failed or returned invalid link: %s", message)
        return None
    except Exception as exc:
        logger.exception("Google Drive upload raised an exception: %s", exc)
        return None


def _post_to_messaging_platform(
    name: str,
    integration_cls,
    post_or_file: str,
    app_settings: AppSettings,
    root_directory: Path,
    week: int,
    report_pdf: Path,
    google_drive_link: Optional[str],
) -> None:
    try:
        integration = integration_cls(app_settings, root_directory, week)

        if post_or_file == "post":
            if not google_drive_link:
                logger.warning(
                    "Cannot post Google Drive link to %s — upload failed or was disabled.",
                    name,
                )
                return
            response = integration.post_message(google_drive_link)

        elif post_or_file == "file":
            response = integration.upload_file(report_pdf)

        else:
            logger.error(
                'Unsupported %s setting: %s_POST_OR_FILE=%s. Expected "post" or "file".',
                name,
                name.upper(),
                post_or_file,
            )
            raise RuntimeError(
                f"Invalid configuration for {name}: {name.upper()}_POST_OR_FILE must be 'post' or 'file'."
            )

        if _is_successful_response(name, response):
            logger.info("Report successfully posted to %s", name)
        else:
            logger.error("Report was NOT posted to %s. Response: %s", name, response)

    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Unexpected error while posting to %s: %s", name, exc)


def _is_successful_response(platform: str, response) -> bool:
    if response is None:
        return False
    if platform == "slack":
        return isinstance(response, dict) and response.get("ok") is True
    if platform == "groupme":
        if response == 202:
            return True
        if isinstance(response, dict):
            return response.get("meta", {}).get("code") in (201, 202)
        return False
    if platform == "discord":
        return isinstance(response, dict) and response.get("type") == 0
    return False


# ---------------------------------------------------------------------------
# League / platform / week selection
# ---------------------------------------------------------------------------
def select_league(
    settings: AppSettings,
    use_default: bool,
    platform: Optional[str],
    game_id: Optional[str | int],
    league_id: Optional[str],
    season: Optional[int],
    start_week: Optional[int],
    week_for_report: Optional[int],
    break_ties: bool,
    playoff_prob_sims: Optional[int],
    dq_ce: bool,
    save_data: bool,
    refresh_feature_web_data: bool,
    offline: bool,
    test: bool,
) -> FantasyFootballReport:
    # Force defaults in non-interactive environments
    if not sys.stdin.isatty() and not use_default:
        logger.warning(
            "Non-interactive environment detected. Falling back to default settings."
        )
        use_default = True

    if use_default:
        os.environ["USE_DEFAULT"] = "1"

    if not platform:
        platform = select_platform(settings, use_default=use_default)

    if week_for_report is None:
        week_for_report = select_week(settings, use_default=use_default)

    if not league_id:
        if use_default:
            logger.info('Using default league (use_default=True).')
        else:
            league_id = _prompt_for_league_id()

    return FantasyFootballReport(
        settings=settings,
        week_for_report=week_for_report,
        platform=platform,
        league_id=league_id,
        game_id=game_id,
        season=season,
        start_week=start_week,
        playoff_prob_sims=playoff_prob_sims,
        break_ties=break_ties,
        dq_ce=dq_ce,
        save_data=save_data,
        refresh_feature_web_data=refresh_feature_web_data,
        offline=offline,
        test=test,
    )


def select_platform(settings: AppSettings, use_default: bool = False) -> str:
    if not sys.stdin.isatty() and not use_default:
        use_default = True

    if use_default:
        logger.info('Using default platform: %s', settings.platform)
        return settings.platform

    selection = input(
        f"{Fore.YELLOW}Generate report for default platform? "
        f"({Fore.GREEN}y{Fore.YELLOW}/{Fore.RED}n{Fore.YELLOW}) -> {Style.RESET_ALL}"
    ).strip().lower()

    if selection == "y":
        if settings.platform in settings.supported_platforms_list:
            return settings.platform
        raise RuntimeError(f"Default platform '{settings.platform}' is not supported.")

    if selection == "n":
        choices = f"{Fore.YELLOW}/{Fore.GREEN}".join(settings.supported_platforms_list)
        chosen = input(
            f"{Fore.YELLOW}For which platform would you like to generate a report? "
            f"({Fore.GREEN}{choices}{Fore.YELLOW}) -> {Style.RESET_ALL}"
        ).strip().lower()
        if chosen in settings.supported_platforms_list:
            return chosen
        raise RuntimeError(f"Unsupported platform selected: '{chosen}'")

    raise RuntimeError("Invalid platform selection. Please answer 'y' or 'n'.")


def select_week(settings: AppSettings, use_default: bool = False) -> int:
    fallback = settings.current_nfl_week or 1
    if use_default:
        logger.info("Using default NFL week: %s", fallback)
    return fallback


def _prompt_for_league_id() -> str:
    selection = input(
        f"{Fore.YELLOW}Generate report for default league? "
        f"({Fore.GREEN}y{Fore.YELLOW}/{Fore.RED}n{Fore.YELLOW}) -> {Style.RESET_ALL}"
    ).strip().lower()

    if selection == "y":
        return None  # let FantasyFootballReport use the default

    if selection == "n":
        league_id = input(
            f"{Fore.YELLOW}What is the league ID of the league for which you want to generate a report? "
            f"-> {Style.RESET_ALL}"
        ).strip()
        if not league_id:
            raise RuntimeError("League ID cannot be empty.")
        return league_id

    raise RuntimeError("Invalid selection. Please answer 'y' or 'n'.")


# ---------------------------------------------------------------------------
# Server & CLI
# ---------------------------------------------------------------------------
def serve_trigger_server(app_settings: AppSettings) -> None:
    # Prefer the PORT that Railway (or any PaaS) injects.
    # Fall back to 8080 only for local development.
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))

    logger.info("Starting Fantasy Football Metrics trigger server on %s:%s", host, port)
    logger.info("Environment → HOST=%s  PORT=%s", host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        log_config=None,
    )


def configure_parser(app_settings: AppSettings) -> ArgumentParser:
    parser = ArgumentParser(
        prog="python main.py",
        description=(
            "The Fantasy Football Metrics Weekly Report application automatically generates a report "
            "in the form of a PDF file that contains a host of metrics and rankings for teams in a "
            "given fantasy football league."
        ),
        epilog="The FFWMR is developed and maintained by Wren J. R. (uberfastman).",
        formatter_class=lambda prog: HelpFormatter(prog, max_help_position=40, width=120),
    )

    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run a long-lived trigger server instead of a one-shot report.",
    )

    # Report configuration
    report_group = parser.add_argument_group("report generation (optional)")
    report_group.add_argument(
        "-p", "--fantasy-platform",
        metavar="<platform>",
        type=str,
        help=f"Fantasy football platform. Supported: {', '.join(app_settings.supported_platforms_list)}",
    )
    report_group.add_argument("-l", "--league-id", metavar="<league_id>", type=str)
    report_group.add_argument(
        "-g", "--yahoo-game-id",
        metavar="<yahoo_game_id>",
        type=str,
        help='(Yahoo only) Game ID. Defaults to "nfl".',
    )
    report_group.add_argument("-y", "--year", metavar="<YYYY>", type=int)
    report_group.add_argument("-k", "--start-week", metavar="<league_start_week>", type=int)
    report_group.add_argument("-w", "--week", metavar="<week>", type=int)
    report_group.add_argument(
        "-d", "--use-default",
        action="store_true",
        help="Run using default settings from .env without user input.",
    )

    # Run options
    run_group = parser.add_argument_group("report run (optional)")
    run_group.add_argument("-s", "--save-data", action="store_true")
    run_group.add_argument("-r", "--refresh-feature-web-data", action="store_true")
    run_group.add_argument("-m", "--playoff-prob-sims", metavar="<num_sims>", type=int)
    run_group.add_argument("-b", "--break-ties", action="store_true")
    run_group.add_argument("-q", "--disqualify-coaching-efficiency", action="store_true")

    # Development
    dev_group = parser.add_argument_group("development (optional)")
    dev_group.add_argument("-o", "--offline", action="store_true")
    dev_group.add_argument("-u", "--skip-uploads", action="store_true")
    dev_group.add_argument("-t", "--test", action="store_true")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    root_directory = Path(__file__).parent
    app_settings = get_app_settings_from_env_file(root_directory / ".env")

    parser = configure_parser(app_settings)
    args = parser.parse_args()

    # Force defaults when running non-interactively (cron, CI, etc.)
    if not args.serve and not sys.stdin.isatty():
        args.use_default = True

    if args.serve:
        serve_trigger_server(app_settings)
    else:
        # If the user provided almost no arguments, fall back to full defaults
        if (
            not args.use_default
            and not args.fantasy_platform
            and not args.league_id
            and args.week is None
        ):
            defaults = build_default_args(app_settings)
            for key, value in vars(defaults).items():
                if getattr(args, key) is None:
                    setattr(args, key, value)
            args.use_default = True

        try:
            run_report(args, app_settings, root_directory)
        except RuntimeError as exc:
            logger.error("Report generation failed: %s", exc)
            sys.exit(1)
        except Exception:
            logger.exception("Unexpected error during report generation")
            sys.exit(1)