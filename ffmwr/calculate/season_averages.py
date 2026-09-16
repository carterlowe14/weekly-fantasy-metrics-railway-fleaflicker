__author__ = "Wren J. R. (uberfastman)"
__email__ = "uberfastman@uberfastman.dev"

from dataclasses import asdict, is_dataclass
from typing import Any, List

import numpy as np

from ffmwr.calculate.metrics import CalculateMetrics
from ffmwr.report.data import ReportData
from ffmwr.utilities.logger import get_logger

logger = get_logger(__name__, propagate=False)


def _row_to_list(row: Any) -> List[Any]:
    """Normalize a metric row (dataclass or list) into a mutable list.

    Supported shapes:
    - TeamMetricResult-style dataclass: rank, team_name, manager, value
      → [rank, team_name, manager, value]
    - Power-ranking style list: [rank, team_name, manager, ...]
    - Already a plain list
    """
    if is_dataclass(row) and not isinstance(row, type):
        d = asdict(row)
        if "rank" in d and "team_name" in d and "manager" in d:
            value = d.get("value", d.get("points", d.get("tabbu", d.get("fines_total"))))
            base = [d["rank"], d["team_name"], d["manager"], value]
            for k, v in d.items():
                if k not in ("rank", "team_name", "manager", "value", "points", "tabbu", "fines_total"):
                    base.append(v)
            return base
        return list(d.values())

    if isinstance(row, (list, tuple)):
        return list(row)

    logger.warning("Unexpected row type in season average calculator: %s", type(row))
    return [row]


class SeasonAverageCalculator(object):
    def __init__(self, team_names: List[str], report_data: ReportData, break_ties: bool):
        logger.debug("Initializing season averages.")

        self.team_names: List[str] = team_names
        self.report_data: ReportData = report_data
        self.break_ties: bool = break_ties

    def get_average(
        self,
        data: List[List[List[Any]]],
        key: str,
        with_percent: bool = False,
        first_ties: bool = False,
        reverse: bool = True,
    ) -> List[List[Any]]:
        """
        Calculate season averages and attach them to each team's ranking row.

        Always returns a list-of-lists so downstream PDF generation and
        post-processing (luck record, optimal totals, etc.) can mutate rows
        safely. Handles both the newer TeamMetricResult dataclasses and the
        older pure-list format.
        """
        logger.debug('Calculating season average from "%s".', key)

        # 1. Build per-team season averages from the time-series data
        season_average_list: List[List[Any]] = []
        team_index = 0
        for team in data:
            if team_index >= len(self.team_names):
                logger.warning(
                    "Team index %s exceeds available team names (%s). "
                    "Skipping this team (likely eliminated from playoffs).",
                    team_index,
                    len(self.team_names),
                )
                team_index += 1
                continue

            team_name = self.team_names[team_index]
            valid_values = [
                value[1]
                for value in team
                if (value[1] is not None and value[1] != "DQ")
            ]

            if valid_values:
                average = float(np.mean(valid_values))
                season_average_value = f"{average:.2f}"
            else:
                # No valid weekly values (e.g. all DQ) – still emit a row
                season_average_value = "0.00"

            season_average_list.append([team_name, season_average_value])
            team_index += 1

        # 2. Order averages and resolve ties
        ordered_average_values = sorted(
            season_average_list, key=lambda x: float(x[1]), reverse=reverse
        )
        for index, team in enumerate(ordered_average_values):
            ordered_average_values[index] = [index, team[0], team[1]]

        ordered_average_values = CalculateMetrics(None, None, None).resolve_season_average_ties(
            ordered_average_values, with_percent
        )

        # 3. Merge season-average column onto the current week's ranking rows.
        #    Normalize every row to a list first so indexing/mutation is safe.
        current_rows = [_row_to_list(row) for row in getattr(self.report_data, key)]
        ordered_season_average_list: List[List[Any]] = []

        for ordered_team in current_rows:
            # ordered_team is now always [rank, team_name, manager, value, ...]
            team_name = ordered_team[1] if len(ordered_team) > 1 else None

            matched = False
            for team in ordered_average_values:
                if team_name == team[1]:
                    # Format the current-week value if needed
                    if with_percent:
                        raw = ordered_team[3] if len(ordered_team) > 3 else None
                        if raw is not None and raw != "DQ":
                            ordered_team[3] = f"{float(str(raw).replace('%', '')):.2f}%"
                        value = str(team[2])
                    elif key == "data_for_scores":
                        if len(ordered_team) > 3 and ordered_team[3] is not None:
                            ordered_team[3] = f"{float(str(ordered_team[3])):.2f}"
                        value = str(team[2])
                    else:
                        value = str(team[2])

                    # Attach the season-average
                    if key == "data_for_scores":
                        ordered_team.insert(-1 if len(ordered_team) > 4 else len(ordered_team), value)
                    elif key == "data_for_coaching_efficiency" and self.break_ties and first_ties:
                        ordered_team.insert(-2 if len(ordered_team) > 4 else len(ordered_team), value)