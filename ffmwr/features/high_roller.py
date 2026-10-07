__author__ = "Wren J. R. (uberfastman)"
__email__ = "uberfastman@uberfastman.dev"

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from bs4 import BeautifulSoup

from ffmwr.features.base.feature import BaseFeature
from ffmwr.utilities.constants import (
    nfl_team_abbreviation_conversions,
    nfl_team_abbreviations,
    nfl_team_names_to_abbreviations,
)
from ffmwr.utilities.logger import get_logger
from ffmwr.utilities.settings import AppSettings, get_app_settings_from_env_file
from ffmwr.utilities.utils import generate_normalized_player_key

logger = get_logger(__name__, propagate=False)

SPOTRAC_API_BASE_URL = "https://api.parse.bot/scraper/6f2b29c4-02ed-41ed-9164-54fe8ea17ee2"


class HighRollerFeature(BaseFeature):
    def __init__(
        self,
        season: int,
        week_for_report: int,
        data_dir: Path,
        refresh: bool = False,
        save_data: bool = False,
        offline: bool = False,
    ):
        """Initialize the High Roller feature and load cached Spotrac player IDs."""
        self.season: int = season
        self.player_identity_cache_path = Path(data_dir) / "spotrac_player_ids.json"
        self.player_identity_cache = self._load_player_identity_cache()
        self.player_fines_cache_path = Path(data_dir) / "spotrac_player_fines.json"
        self.player_fines_cache = self._load_json_cache(self.player_fines_cache_path)
        self.credit_usage_path = Path(data_dir) / "spotrac_credit_usage.json"
        self.monthly_credit_usage = self._load_json_cache(self.credit_usage_path)
        self._attempted_player_keys = set()
        self._public_scrape_available = False

        defense = {
            "CB": "D",
            "DE": "D",
            "DT": "D",
            "FS": "D",
            "ILB": "D",
            "LB": "D",
            "OLB": "D",
            "S": "D",
            "SS": "D",
        }
        offense = {
            "FB": "O",
            "QB": "O",
            "RB": "O",
            "TE": "O",
            "WR": "O",
        }
        special_teams = {
            "K": "S",
            "P": "S",
        }
        offensive_line = {
            "C": "L",
            "G": "L",
            "LS": "L",
            "LT": "L",
            "RT": "L",
        }
        team_defense = {
            "D/ST": "D",
        }
        # position type reference
        self.position_types: Dict[str, str] = {
            **defense,
            **offense,
            **special_teams,
            **offensive_line,
            **team_defense,
        }

        super().__init__(
            "high_roller",
            SPOTRAC_API_BASE_URL,
            week_for_report,
            data_dir,
            True,  # TODO: decide if team D/ST roll-ups should be included in high roller total
            refresh,
            save_data,
            offline,
        )

    def _call_spotrac_api(self, endpoint: str, params: Dict[str, str | int]):
        api_key = os.getenv("SPOTRAC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SPOTRAC_API_KEY is required to call the Spotrac Parse API.")

        credit_cost = {"search_players": 1, "get_player_fines": 3}.get(endpoint)
        if credit_cost is None:
            raise ValueError(f"Unknown Spotrac Parse endpoint: {endpoint}")
        self._reserve_spotrac_credits(credit_cost)

        response = requests.get(
            f"{SPOTRAC_API_BASE_URL}/{endpoint}",
            headers={"X-API-Key": api_key},
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _load_json_cache(self, cache_path: Path) -> Dict[str, Any]:
        try:
            with cache_path.open(encoding="utf-8") as cache_file:
                cache = json.load(cache_file)
            return cache if isinstance(cache, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to read Spotrac cache %s: %s", cache_path.name, exc)
            return {}

    @staticmethod
    def _write_json_cache(cache_path: Path, cache: Dict[str, Any]) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    def _reserve_spotrac_credits(self, cost: int) -> None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        used = int(self.monthly_credit_usage.get(month, 0))
        monthly_limit = self._spotrac_monthly_credit_limit()
        if used + cost > monthly_limit:
            raise RuntimeError(
                f"Spotrac Parse monthly credit limit reached ({used}/{monthly_limit}); "
                "skipping paid fallback call."
            )

        self.monthly_credit_usage[month] = used + cost
        self._write_json_cache(self.credit_usage_path, self.monthly_credit_usage)

    @staticmethod
    def _spotrac_monthly_credit_limit() -> int:
        try:
            return max(0, int(os.getenv("SPOTRAC_MONTHLY_CREDIT_LIMIT", "300")))
        except ValueError:
            return 300

    def _can_reserve_spotrac_credits(self, cost: int) -> bool:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        used = int(self.monthly_credit_usage.get(month, 0))
        return used + cost <= self._spotrac_monthly_credit_limit()

    def search_players(self, query: str):
        return self._call_spotrac_api("search_players", {"query": query})

    def get_player_fines(self, player_id: str | int, player_slug: str, year: int):
        return self._call_spotrac_api(
            "get_player_fines",
            {"player_id": str(player_id), "player_slug": player_slug, "year": year},
        )

    def _load_player_identity_cache(self) -> Dict[str, Dict[str, str]]:
        try:
            with self.player_identity_cache_path.open(encoding="utf-8") as cache_file:
                cache = json.load(cache_file)
            return cache if isinstance(cache, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to read cached Spotrac player IDs: %s", exc)
            return {}

    def _save_player_identity_cache(self) -> None:
        self.player_identity_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.player_identity_cache_path.write_text(
            json.dumps(self.player_identity_cache, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _player_name_key(name: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")

    @classmethod
    def _player_slug(cls, name: str) -> str:
        return cls._player_name_key(name).replace("_", "-")

    @staticmethod
    def _amount_value(value: Any) -> float:
        if isinstance(value, str):
            value = re.sub(r"[^0-9.]", "", value)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _find_player_identity(self, player_name: str, player_team_abbr: str) -> Optional[Dict[str, str]]:
        search_response = self.search_players(player_name)
        search_data = search_response.get("data") or {}
        results = search_data.get("results") or []
        target_name = self._player_name_key(player_name)

        exact_matches = [
            player for player in results
            if self._player_name_key(str(player.get("name", ""))) == target_name
        ]
        if not exact_matches:
            exact_matches = [
                player for player in results
                if self._player_name_key(str(player.get("name", ""))).startswith(f"{target_name}nfl")
            ]
        if not exact_matches:
            return None

        team_name = next(
            (
                name
                for name, abbreviation in nfl_team_names_to_abbreviations.items()
                if abbreviation == player_team_abbr
            ),
            None,
        )
        if team_name:
            matching_team = [
                player
                for player in exact_matches
                if team_name.casefold()
                in f"{player.get('team', '')} {player.get('team_name', '')} {player.get('name', '')}".casefold()
            ]
            if matching_team:
                exact_matches = matching_team
            else:
                results_include_nfl_teams = any(
                    nfl_team.casefold()
                    in f"{player.get('team', '')} {player.get('team_name', '')} {player.get('name', '')}".casefold()
                    for player in exact_matches
                    for nfl_team in nfl_team_names_to_abbreviations
                )
                if results_include_nfl_teams or len(exact_matches) > 1:
                    return None

        match = exact_matches[0]
        player_id = match.get("player_id") or match.get("id")
        if not player_id:
            return None

        player_slug = match.get("player_slug") or match.get("slug") or self._player_slug(player_name)
        return {"player_id": str(player_id), "player_slug": str(player_slug)}

    def _ensure_player_fines(
        self,
        player_first_name: str,
        player_last_name: str,
        player_team_abbr: str,
        player_position: str,
    ) -> None:
        if self.offline or player_position == "D/ST":
            return

        player_name = f"{player_first_name or ''} {player_last_name or ''}".strip()
        team_abbr = (player_team_abbr or "?").upper()
        team_abbr = nfl_team_abbreviation_conversions.get(team_abbr, team_abbr)
        player_key = generate_normalized_player_key(player_name, team_abbr)
        if player_key in self._attempted_player_keys:
            return
        self._attempted_player_keys.add(player_key)

        if self._public_scrape_available:
            return

        identity = self.player_identity_cache.get(player_key)
        if not identity:
            if not self._can_reserve_spotrac_credits(4):
                logger.warning(
                    "Skipping Spotrac lookup for %s: fewer than four Parse credits remain for ID search and fines.",
                    player_name,
                )
                return
            try:
                identity = self._find_player_identity(player_name, team_abbr)
            except Exception as exc:
                logger.warning("Unable to find Spotrac ID for %s: %s", player_name, exc)
                return
            if not identity:
                logger.warning("No Spotrac player match found for %s; skipping fines lookup.", player_name)
                return
            self.player_identity_cache[player_key] = identity
            try:
                self._save_player_identity_cache()
            except OSError as exc:
                logger.warning("Unable to save cached Spotrac player IDs: %s", exc)

        fines_cache_key = f"{self.season}:{identity['player_id']}"
        cache_entry = self.player_fines_cache.get(fines_cache_key)
        data = None
        if cache_entry and not self.refresh:
            try:
                fetched_at = datetime.fromisoformat(cache_entry["fetched_at"])
                if datetime.now(timezone.utc) - fetched_at < timedelta(days=30):
                    data = cache_entry["data"]
            except (KeyError, TypeError, ValueError):
                data = None

        if data is None:
            try:
                response = self.get_player_fines(identity["player_id"], identity["player_slug"], self.season)
            except Exception as exc:
                logger.warning("Unable to retrieve Spotrac fines for %s: %s", player_name, exc)
                return

            data = response.get("data") or {}
            self.player_fines_cache[fines_cache_key] = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
            try:
                self._write_json_cache(self.player_fines_cache_path, self.player_fines_cache)
            except OSError as exc:
                logger.warning("Unable to save cached Spotrac fines: %s", exc)

        fines = data.get("fines") or []
        fine_count = int(data.get("fine_count") or len(fines))
        fines_total = self._amount_value(data.get("total_amount"))

        detailed_fines = []
        for fine in fines:
            amount = next(
                (fine[key] for key in ("amount", "fine_amount", "fineAmount", "fine") if fine.get(key) is not None),
                0,
            )
            violation = next(
                (fine[key] for key in ("violation", "description", "reason", "type") if fine.get(key)),
                None,
            )
            detailed_fines.append((self._amount_value(amount), violation))

        if detailed_fines:
            worst_fine, worst_violation = max(detailed_fines, key=lambda entry: entry[0])
        else:
            worst_fine = 0.0
            worst_violation = "Fine details unavailable" if fine_count else None

        position_type = self.position_types.get(player_position, "U")
        player_data = {
            **self._get_feature_data_template(player_name, team_abbr, player_position, position_type),
            "fines": fines,
            "fines_count": fine_count,
            "fines_total": fines_total,
            "worst_violation": worst_violation,
            "worst_violation_fine": worst_fine,
        }
        self.feature_data[player_key] = player_data
        self.raw_feature_data[player_key] = data

        team_data = self.feature_data.get(team_abbr)
        if team_data and player_key not in team_data["players"]:
            team_data["players"][player_key] = player_data
            team_data["violators"].append(player_name)
            team_data["violators_count"] = len(team_data["violators"])
            team_data["fines_count"] += fine_count
            team_data["fines_total"] += fines_total
            if worst_fine > team_data["worst_violation_fine"]:
                team_data["worst_violation"] = worst_violation
                team_data["worst_violation_fine"] = worst_fine

        self._save_feature_data()

    def _normalize_team_abbr(self, team_name: Optional[str]) -> Optional[str]:
        if not team_name:
            return None
        team_name = team_name.strip()
        upper_name = team_name.upper()
        if upper_name in nfl_team_abbreviations:
            return upper_name
        if upper_name in nfl_team_abbreviation_conversions:
            return nfl_team_abbreviation_conversions[upper_name]
        return next(
            (
                abbreviation
                for full_name, abbreviation in nfl_team_names_to_abbreviations.items()
                if full_name.casefold() == team_name.casefold()
            ),
            None,
        )

    def _add_public_fine_row(self, row) -> bool:
        name_element = row.find("a", {"class": "link"})
        player_name = name_element.get_text(" ", strip=True) if name_element else ""
        if not player_name:
            return False

        team_element = row.find("td", {"class": "fines-team"})
        if not team_element:
            team_element = row.find("td", {"class": "text-left details"})
        image_element = team_element.find("img") if team_element else None
        team_value = team_element.get_text(" ", strip=True) if team_element else None
        team_abbr = self._normalize_team_abbr(team_value)
        if not team_abbr:
            team_abbr = self._normalize_team_abbr(image_element.get("alt") if image_element else None)
        if not team_abbr:
            return False

        amount_element = row.find("td", {"class": "fines-amount"})
        if not amount_element:
            amount_element = row.find("td", {"class": "text-center details highlight"})
        if not amount_element:
            return False
        amount = self._amount_value(amount_element.get_text(" ", strip=True))
        if amount <= 0:
            return False

        position_element = row.find("td", {"class": "fines-position"})
        if not position_element:
            position_element = row.find("td", {"class": "text-left details-sm"})
        position = position_element.get_text(" ", strip=True) if position_element else "Unknown"
        position_type = self.position_types.get(position, "U")

        infraction_element = row.find("td", {"class": "fines-infraction"})
        violation_element = infraction_element.find("span", {"class": "text-muted"}) if infraction_element else None
        if violation_element:
            violation = violation_element.get_text(" ", strip=True)
        elif infraction_element:
            violation = re.sub(r"^Fine\s*", "", infraction_element.get_text(" ", strip=True))
        else:
            violation = None
        violation = re.sub(r"^[\s/:–—-]+", "", violation) if violation else None

        date_element = row.find("td", {"class": "fines-date"})
        if not date_element:
            date_element = row.find("td", {"class": "text-right details"})
        violation_date = date_element.get_text(" ", strip=True) if date_element else None
        if violation_date:
            for date_format in ("%m/%d/%y", "%m/%d/%Y"):
                try:
                    violation_date = datetime.strptime(violation_date, date_format).isoformat()
                    break
                except ValueError:
                    continue

            week_element = row.find("td", {"class": "fines-week"})
            week = week_element.get_text(" ", strip=True) if week_element else None

        fine = {
            "violation": violation,
            "violation_fine": amount,
            "violation_season": self.season,
            "violation_date": violation_date,
        }
        player_key = generate_normalized_player_key(player_name, team_abbr)
        fingerprint = (player_key, amount, violation, violation_date, week)
        if fingerprint in self._scraped_fine_fingerprints:
            return False
        self._scraped_fine_fingerprints.add(fingerprint)

        player_data = self.feature_data.get(player_key)
        if not player_data:
            player_data = {
                **self._get_feature_data_template(player_name, team_abbr, position, position_type),
                "fines": [],
                "fines_count": 0,
                "fines_total": 0.0,
                "worst_violation": None,
                "worst_violation_fine": 0.0,
            }
            self.feature_data[player_key] = player_data

        player_data["fines"].append(fine)
        player_data["fines_count"] += 1
        player_data["fines_total"] += amount
        if amount >= player_data["worst_violation_fine"]:
            player_data["worst_violation"] = violation
            player_data["worst_violation_fine"] = amount
        self.raw_feature_data[player_key] = row.get_text(" ", strip=True)

        profile_url = name_element.get("href", "")
        profile_match = re.search(r"/id/(\d+)/([^/?#]+)", profile_url)
        if profile_match:
            self.player_identity_cache[player_key] = {
                "player_id": profile_match.group(1),
                "player_slug": profile_match.group(2),
            }
        return True

    def _scrape_public_fines(self) -> bool:
        url = f"https://www.spotrac.com/nfl/fines-suspensions/_/year/{self.season}"
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": (
                        "FantasyFootballMetricsWeeklyReport/1.0 "
                        "(+https://github.com/carterlowe14/weekly-fantasy-metrics-railway-fleaflicker)"
                    )
                },
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Spotrac public fines page unavailable; Parse fallback may be used: %s", exc)
            return False

        soup = BeautifulSoup(response.text, "html.parser")
        table_body = soup.find("tbody")
        if table_body is None:
            title = soup.title.get_text(" ", strip=True) if soup.title else None
            logger.warning("Spotrac public fines page had no table (title=%r).", title)
            return False

        rows = table_body.find_all("tr")
        self._scraped_fine_fingerprints = set()
        parsed_rows = sum(1 for row in rows if self._add_public_fine_row(row))
        if not parsed_rows:
            logger.warning("Spotrac public fines table contained no parseable player rows.")
            return False

        for player_key, player in list(self.feature_data.items()):
            if player.get("position") == "D/ST":
                continue
            team_data = self.feature_data.get(player["team_abbr"])
            if not team_data:
                continue
            team_data["players"][player_key] = player
            team_data["violators"].append(player["full_name"])
            team_data["violators_count"] += 1
            team_data["fines_count"] += player["fines_count"]
            team_data["fines_total"] += player["fines_total"]
            if player["worst_violation_fine"] > team_data["worst_violation_fine"]:
                team_data["worst_violation"] = player["worst_violation"]
                team_data["worst_violation_fine"] = player["worst_violation_fine"]

        self._public_scrape_available = True
        try:
            self._save_player_identity_cache()
        except OSError as exc:
            logger.warning("Unable to save player IDs discovered from Spotrac's public page: %s", exc)
        logger.info("Retrieved %s player fine rows from Spotrac's public page without Parse credits.", parsed_rows)
        return True

    # noinspection PyCallingNonCallable
    def _get_feature_data(self):
        for team in nfl_team_abbreviations:
            self.feature_data[team] = {
                "position": "D/ST",
                "players": {},
                "violators": [],
                "violators_count": 0,
                "fines_count": 0,
                "fines_total": 0.0,
                "worst_violation": None,
                "worst_violation_fine": 0.0,
            }
        if not self._scrape_public_fines():
            logger.info("High Roller will use the credit-limited Parse fallback for active lineup players.")
        elif self.save_data:
            self._save_feature_data()

    def get_player_worst_violation(
        self, player_first_name: str, player_last_name: str, player_team_abbr: str, player_position: str
    ) -> str:
        self._ensure_player_fines(player_first_name, player_last_name, player_team_abbr, player_position)
        return self._get_player_feature_stats(
            player_first_name, player_last_name, player_team_abbr, player_position, "worst_violation", str
        )

    def get_player_worst_violation_fine(
        self, player_first_name: str, player_last_name: str, player_team_abbr: str, player_position: str
    ) -> float:
        self._ensure_player_fines(player_first_name, player_last_name, player_team_abbr, player_position)
        return self._get_player_feature_stats(
            player_first_name, player_last_name, player_team_abbr, player_position, "worst_violation_fine", float
        )

    def get_player_fines_total(
        self, player_first_name: str, player_last_name: str, player_team_abbr: str, player_position: str
    ) -> float:
        self._ensure_player_fines(player_first_name, player_last_name, player_team_abbr, player_position)
        return self._get_player_feature_stats(
            player_first_name, player_last_name, player_team_abbr, player_position, "fines_total", float
        )

    def get_player_num_violators(
        self, player_first_name: str, player_last_name: str, player_team_abbr: str, player_position: str
    ) -> int:
        self._ensure_player_fines(player_first_name, player_last_name, player_team_abbr, player_position)
        return self._get_player_feature_stats(
            player_first_name, player_last_name, player_team_abbr, player_position, "fines_count", int
        )


if __name__ == "__main__":
    local_root_directory = Path(__file__).parent.parent.parent

    local_settings: AppSettings = get_app_settings_from_env_file(local_root_directory / ".env")

    local_high_roller_feature = HighRollerFeature(
        local_settings.season,
        1,
        local_root_directory / local_settings.data_dir_path / "tests" / "feature_data",
        refresh=True,
        save_data=True,
        offline=False,
    )
