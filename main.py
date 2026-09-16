__author__ = "Wren J. R. (uberfastman)"
__email__ = "uberfastman@uberfastman.dev"

import sys

if not sys.warnoptions:
    import warnings

    # suppress SyntaxWarning due to "invalid escape sequence" messages in transitive dependencies: rauth, stringcase
    warnings.filterwarnings("ignore", category=SyntaxWarning)

import os
import colorama
import secrets
import time
from argparse import ArgumentParser, HelpFormatter, Namespace
from colorama import Fore, Style
from datetime import datetime
from importlib.metadata import distributions
from pathlib import Path
from tomllib import load as load_toml
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from ffmwr.integrations.discord import DiscordIntegration
from ffmwr.integrations.drive import GoogleDriveIntegration
from ffmwr.integrations.groupme import GroupMeIntegration
from ffmwr.integrations.slack import SlackIntegration
from ffmwr.report.builder import FantasyFootballReport
from ffmwr.utilities.app import check_github_for_updates
from ffmwr.utilities.logger import get_logger
from ffmwr.utilities.settings import AppSettings, get_app_settings_from_env_file
from ffmwr.utilities.utils import format_platform_display, normalize_dependency_package_name

colorama.init()

logger = get_logger()


app = FastAPI(title="Fantasy Football Metrics Weekly Report Trigger")

TRIGGER_SECRET = os.getenv("TRIGGER_SECRET")

if not TRIGGER_SECRET:
    logger.warning(
        'TRIGGER_SECRET is not set. The "/trigger" endpoint is UNAUTHENTICATED and can be '
        "called by anyone who has the URL. Set TRIGGER_SECRET in the environment to lock it down."
    )


def verify_trigger_secret(x_trigger_secret: Optional[str] = Header(default=None)) -> None:
    if not TRIGGER_SECRET:
        return
    if not x_trigger_secret or not secrets.compare_digest(x_trigger_secret, TRIGGER_SECRET):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Trigger-Secret header.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/trigger")
def trigger_report(x_trigger_secret: Optional[str] = Header(default=None)) -> FileResponse:
    """Always runs with the .env defaults - no per-request configuration accepted."""
    verify_trigger_secret(x_trigger_secret)

    root_directory = Path(__file__).parent
    app_settings: AppSettings = get_app_settings_from_env_file(root_directory / ".env")

    args = build_default_args(app_settings)
    args.skip_uploads = False

    try:
        result = run_report(args, app_settings, root_directory)
    except RuntimeError as e:
        logger.error(f"Report generation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error during report generation.")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    return FileResponse(
        path=result,
        media_type="application/pdf",
        filename=Path(result).name,
    )


def build_default_args(app_settings: AppSettings) -> Namespace:
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


def run_report(args: Namespace, app_settings: AppSettings, root_directory: Path) -> Path:
    if app_settings.check_for_updates:
        check_github_for_updates(args.use_default)

    f_str_newline = "\n"
    args_display = f"{f_str_newline}".join(
        [f"  {k}{'.' * (len(max(vars(args).keys(), key=len)) - len(k))}...{v}" for k, v in vars(args).items()]
    )
    logger.info(
        f"{f_str_newline}"
        f"Generating{' TEST' if args.test else ''} "
        f"{format_platform_display(args.fantasy_platform if args.fantasy_platform else app_settings.platform)} "
        f"Fantasy Football report on {datetime.now().strftime('%b %d, %Y at %I:%M%p')} with the following command line arguments:"
        f"{f_str_newline * 2}"
        f"{args_display}"
        f"{f_str_newline}"
    )

    report = select_league(
        app_settings,
        args.use_default,
        args.fantasy_platform,
        args.yahoo_game_id,
        args.league_id,
        args.year,
        args.start_week,
        args.week,
        args.break_ties,
        args.playoff_prob_sims,
        args.disqualify_coaching_efficiency,
        args.save_data,
        args.refresh_feature_web_data,
        args.offline,
        args.test,
    )
    report_pdf: Path = report.create_pdf_report()

    upload_message = ""
    # Google Drive is handled first as other integrations may use its upload link
    if app_settings.integration_settings.google_drive_upload_bool:
        if not args.skip_uploads and not args.test:
            google_drive_integration = GoogleDriveIntegration(
                app_settings, root_directory, report.league.week_for_report
            )
            upload_message = google_drive_integration.upload_file(report_pdf)
            logger.info(upload_message)
        else:
            logger.info(f"Report NOT uploaded to Google Drive with command line arguments: {args}")

    # Other integrations that support both posting links and uploading files
    msg_integrations = [
        ("slack", app_settings.integration_settings.slack_post_bool, SlackIntegration,
         app_settings.integration_settings.slack_post_or_file),
        ("groupme", app_settings.integration_settings.groupme_post_bool, GroupMeIntegration,
         app_settings.integration_settings.groupme_post_or_file),
        ("discord", app_settings.integration_settings.discord_post_bool, DiscordIntegration,
         app_settings.integration_settings.discord_post_or_file),
    ]

    for name, enabled, integration_class, post_or_file in msg_integrations:
        if not enabled:
            continue

        if not args.skip_uploads and not args.test:
            integration = integration_class(app_settings, root_directory, report.league.week_for_report)

            if post_or_file == "post":
                if app_settings.integration_settings.google_drive_upload_bool:
                    response = integration.post_message(upload_message)
                else:
                    logger.warning(f"Unable to post Google Drive link to {name} when GOOGLE_DRIVE_UPLOAD_BOOL=False.")
                    response = None
            elif post_or_file == "file":
                response = integration.upload_file(report_pdf)
            else:
                logger.warning(
                    f'The ".env" file contains unsupported {name} setting: '
                    f'{name.upper()}_POST_OR_FILE={post_or_file}. Please choose "post" or "file" and try again.'
                )
                raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")

            # Validate response based on platform
            is_success = False
            if name == "slack" and response and response.get("ok"):
                is_success = True
            elif name == "groupme" and (response == 202 or (isinstance(response, dict) and response.get("meta", {}).get("code") == 201)):
                is_success = True
            elif name == "discord" and response and response.get("type") == 0:
                is_success = True

            if is_success:
                logger.info(f"Report {str(report_pdf)} successfully posted to {name}!")
            else:
                logger.error(f"Report {str(report_pdf)} was NOT posted to {name} with error: {response}")
        else:
            logger.info(f"Report NOT posted to {name} with command line arguments: {args}")

    return report_pdf


def select_league(
    settings: AppSettings,
    use_default: bool,
    platform: str,
    game_id: int | str,
    league_id: Optional[str],
    season: int,
    start_week: int,
    week_for_report: int,
    break_ties: bool,
    playoff_prob_sims: int,
    dq_ce: bool,
    save_data: bool,
    refresh_feature_web_data: bool,
    offline: bool,
    test: bool,
) -> FantasyFootballReport:
    if use_default:
        os.environ["USE_DEFAULT"] = "1"
    if not platform:
        platform = select_platform(settings, use_default=use_default)
    if not week_for_report:
        week_for_report = select_week(settings, use_default=use_default)
    if not league_id:
        if not use_default:
            if not sys.stdin.isatty():
                logger.error("League ID is missing and environment is non-interactive. Please provide league_id in .env or via API.")
                raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
            selection = input(f"{Fore.YELLOW}Generate report for default league? ({Fore.GREEN}y{Fore.YELLOW}/{Fore.RED}n{Fore.YELLOW}) -> {Style.RESET_ALL}").lower()
        else:
            logger.info('Use-default is set to "true". Automatically running the report for the default league.')
            selection = "y"
    else:
        selection = "selected"

    if selection == "y":
        return FantasyFootballReport(
            settings=settings,
            week_for_report=week_for_report,
            platform=platform,
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
    elif selection == "n":
        if not sys.stdin.isatty():
            logger.error("Environment is non-interactive. Cannot prompt for league ID.")
            raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
        league_id = input(f"{Fore.YELLOW}What is the league ID of the league for which you want to generate a report? -> {Style.RESET_ALL}")
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
    else:
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
    if use_default:
        logger.info('Use-default is set to "true". Automatically running the report for the default platform.')
        selection = "y"
    else:
        if not sys.stdin.isatty():
            logger.error("Environment is non-interactive. Cannot prompt for platform.")
            raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
        selection = input(f"{Fore.YELLOW}Generate report for default platform? ({Fore.GREEN}y{Fore.YELLOW}/{Fore.RED}n{Fore.YELLOW}) -> {Style.RESET_ALL}").lower()

    if selection == "y":
        if settings.platform in settings.supported_platforms_list:
            return settings.platform
        raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
    elif selection == "n":
        if not sys.stdin.isatty():
            logger.error("Environment is non-interactive. Cannot prompt for platform.")
            raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
        chosen_platform = input(f"{Fore.YELLOW}For which platform would you like to generate a report ? ({Fore.GREEN}{f'{Fore.YELLOW}/{Fore.GREEN}'.join(settings.supported_platforms_list)}{Fore.YELLOW}) -> {Style.RESET_ALL}").lower()
        if chosen_platform in settings.supported_platforms_list:
            return chosen_platform
        raise RuntimeError("Report generation failed due to invalid configuration or missing input; see server logs for details.")
    return settings.platform


def select_week(settings: AppSettings, use_default: bool = False) -> Optional[int]:
    if use_default:
        fallback_week = settings.current_nfl_week or 1
        logger.info(f'Use-default is set to "true". Automatically running the report for NFL week {fallback_week}.')
        return fallback_week
    return settings.current_nfl_week or 1


def serve_trigger_server(app_settings: AppSettings) -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting Fantasy Football Metrics trigger server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def configure_parser(app_settings: AppSettings) -> ArgumentParser:
    arg_parser = ArgumentParser(
        prog="python main.py",
        description=(
            "The Fantasy Football Metrics Weekly Report application automatically generates a report in the form of a "
            "PDF file that contains a host of metrics and rankings for teams in a given fantasy football league."
        ),
        epilog="The FFWMR is developed and maintained by Wren J. R. (uberfastman).",
        formatter_class=lambda prog: HelpFormatter(prog, max_help_position=40, width=120),
        add_help=True,
    )

    arg_parser.add_argument("--serve", action="store_true", help="Run a long-lived trigger server instead of a one-shot report.")

    report_configuration_group = arg_parser.add_argument_group("report generation (optional)")
    report_configuration_group.add_argument("-p", "--fantasy-platform", metavar="<platform>", type=str, required=False,
        help=f"Fantasy football platform on which league for report is hosted. Currently supports: {', '.join(app_settings.supported_platforms_list)}")
    report_configuration_group.add_argument("-l", "--league-id", metavar="<league_id>", type=str, required=False,
        help="Fantasy Football league ID")
    report_configuration_group.add_argument("-g", "--yahoo-game-id", metavar="<yahoo_game_id>", type=str, required=False,
        help='(Yahoo only) Chosen fantasy game id for which to generate report. Defaults to "nfl"')
    report_configuration_group.add_argument("-y", "--year", metavar="<YYYY>", type=int, required=False,
        help="Chosen year (season) of the league for which a report is being generated")
    report_configuration_group.add_argument("-k", "--start-week", metavar="<league_start_week>", type=int, required=False,
        help="League start week (if league started later than week 1)")
    report_configuration_group.add_argument("-w", "--week", metavar="<week>", type=int, required=False,
        help="Chosen week for which to generate report")
    report_configuration_group.add_argument("-d", "--use-default", action="store_true", required=False,
        help="Run the report using the default settings (in .env file) without user input")

    report_run_group = arg_parser.add_argument_group("report run (optional)")
    report_run_group.add_argument("-s", "--save-data", action="store_true", required=False, help="Save all fantasy league data for faster future report generation")
    report_run_group.add_argument("-r", "--refresh-feature-web-data", action="store_true", required=False, help="Refresh all feature web data")
    report_run_group.add_argument("-m", "--playoff-prob-sims", metavar="<num_sims>", type=int, required=False, help="Number of Monte Carlo playoff probability simulations to run")
    report_run_group.add_argument("-b", "--break-ties", action="store_true", required=False, help="Break ties in metric rankings")
    report_run_group.add_argument("-q", "--disqualify-coaching-efficiency", action="store_true", required=False, help="Automatically disqualify teams ineligible for coaching efficiency metric")

    development_group = arg_parser.add_argument_group("development (optional)")
    development_group.add_argument("-o", "--offline", action="store_true", required=False, help="Run OFFLINE for development (must have previously run report with -s option)")
    development_group.add_argument("-u", "--skip-uploads", action="store_true", required=False, help="Skip all integration uploads regardless of the configured settings")
    development_group.add_argument("-t", "--test", action="store_true", required=False, help="Generate TEST report")

    return arg_parser


if __name__ == "__main__":
    root_directory = Path(__file__).parent
    app_settings: AppSettings = get_app_settings_from_env_file(root_directory / ".env")
    arg_parser = configure_parser(app_settings)
    args: Namespace = arg_parser.parse_args()

    if args.serve:
        serve_trigger_server(app_settings)
    else:
        if not args.use_default and not args.fantasy_platform and not args.league_id and not args.week:
            defaults = build_default_args(app_settings)
            for k, v in vars(defaults).items():
                if getattr(args, k) is None:
                    setattr(args, k, v)
            args.use_default = True
        run_report(args, app_settings, root_directory)
