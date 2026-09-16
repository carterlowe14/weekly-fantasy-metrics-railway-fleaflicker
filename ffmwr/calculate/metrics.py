__author__ = "Wren J. R. (uberfastman)"
__email__ = "uberfastman@uberfastman.dev"

import itertools
from collections import OrderedDict, defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional

import numpy as np

from ffmwr.models.base.model import BaseLeague, BasePlayer, BaseRecord, BaseTeam, TeamMetricResult, BadBoyResult, BeefResult, HighRollerResult
from ffmwr.utilities.logger import get_logger

logger = get_logger(__name__, propagate=False)


class CalculateMetrics(object):
    def __init__(
        self, league_id: Optional[str], playoff_slots: int | None, playoff_simulations: int | None
    ):
        logger.debug("Initializing metrics calculator.")

        self.league_id: str = league_id
        self.playoff_slots: int = playoff_slots
        self.playoff_simulations: int = playoff_simulations
        self.coaching_efficiency_dq_count: int = 0

    @staticmethod
    def decode_byte_string(byte_string: bytes | str) -> bytes | str:
        try:
            return byte_string.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            return byte_string

    @staticmethod
    def get_standings_data(league: BaseLeague) -> List[List[Any]]:
        logger.debug("Creating league standings data.")

        current_standings_data = []
        team: BaseTeam
        for team in league.standings:
            team_current_standings_data = [
                team.record.rank,
                team.name,
                team.manager_str,
                (
                    f"{team.record.get_wins()}-{team.record.get_losses()}-{team.record.get_ties()} "
                    f"({team.record.get_percentage()})"
                ),
                f"{team.record.get_points_for():.2f}",
                f"{team.record.get_points_against():.2f}",
                team.record.get_streak_str(),
                team.waiver_priority if not league.is_faab else f"${int(team.faab)}",
                team.num_moves,
                team.num_trades,
            ]
            if league.is_faab:
                team_current_standings_data.insert(7, team.waiver_priority)

            current_standings_data.append(team_current_standings_data)

        return current_standings_data

    @staticmethod
    def get_division_standings_data(league: BaseLeague) -> List[List[List[Any]]]:
        logger.debug("Creating league division standings data.")

        # group teams into divisions
        division_groups = defaultdict(list)
        for team in league.standings:
            division_groups[str(team.division)].append(team)

        # sort the teams
        sorted_divisions = {}
        for division_id, teams in division_groups.items():
            sorted_divisions[division_id] = sorted(
                teams,
                key=lambda x: (
                    x.record.get_wins(),
                    -x.record.get_losses(),
                    x.record.get_ties(),
                    x.record.get_division_wins(),
                    -x.record.get_division_losses(),
                    x.record.get_division_ties(),
                    float(x.record.get_points_for()),
                ),
                reverse=True,
            )

        # TODO: figure out how to get this ranking right
        ranked_division_teams = []
        for division in sorted_divisions.values():
            for team in division:
                ranked_division_teams.append(team)
        ranked_division_teams = sorted(
            ranked_division_teams,
            key=lambda x: (
                x.record.get_wins(),
                -x.record.get_losses(),
                x.record.get_ties(),
                x.record.get_division_wins(),
                -x.record.get_division_losses(),
                x.record.get_division_ties(),
                float(x.record.get_points_for()),
            ),
            reverse=True,
        )
        team_ranks_by_id = {}
        rank = 1
        for team in ranked_division_teams:
            team_ranks_by_id[team.team_id] = rank
            rank += 1

        modified_team_names = defaultdict()
        current_division_standings_data = []
        for division in sorted_divisions.values():
            division_standings_data = []
            team: BaseTeam
            for team in division:
                if division.index(team) == 0:
                    modified_team_names[team.team_id] = "†"
                else:
                    modified_team_names[team.team_id] = ""

                team_division_standings_data = [
                    team_ranks_by_id[team.team_id],
                    team.name + modified_team_names[team.team_id],
                    team.manager_str,
                    (
                        f"{team.record.get_wins()}-{team.record.get_losses()}-{team.record.get_ties()} "
                        f"({team.record.get_percentage()})"
                    ),
                    (
                        f"{team.record.get_division_wins()}-{team.record.get_division_losses()}"
                        f"-{team.record.get_division_ties()} ({team.record.get_division_percentage()})"
                    ),
                    f"{team.record.get_points_for():.2f}",
                    f"{team.record.get_points_against():.2f}",
                    team.record.get_streak_str(),
                    team.waiver_priority if not league.is_faab else f"${int(team.faab)}",
                    team.num_moves,
                    team.num_trades,
                    str(team.division),  # stored here temporarily to pass team divisions to report generator
                ]
                if league.is_faab and team.waiver_priority != 0:
                    team_division_standings_data.insert(8, team.waiver_priority)

                division_standings_data.append(team_division_standings_data)

            current_division_standings_data.append(division_standings_data)
        return current_division_standings_data

    @staticmethod
    def get_median_standings_data(league: BaseLeague) -> List[List[Any]]:
        logger.debug("Creating league median standings data.")

        current_median_standings_data = []
        rank = 1
        team: BaseTeam
        for team in sorted(
            league.current_median_standings,
            key=lambda x: (
                x.get_combined_record().get_wins(),
                -x.get_combined_record().get_losses(),
                x.get_combined_record().get_ties(),
                x.get_combined_record().get_points_for(),
            ),
            reverse=True,
        ):
            combined_record = team.get_combined_record()
            team_current_median_standings_data = [
                rank,
                team.name,
                team.manager_str,
                (
                    str(combined_record.get_wins())
                    + "-"
                    + str(combined_record.get_losses())
                    + "-"
                    + str(combined_record.get_ties())
                    + " ("
                    + str(combined_record.get_percentage())
                    + ")"
                ),
                (
                    str(team.current_median_record.get_wins())
                    + "-"
                    + str(team.current_median_record.get_losses())
                    + "-"
                    + str(team.current_median_record.get_ties())
                    + " ("
                    + str(team.current_median_record.get_percentage())
                    + ")"
                ),
                f"{round(float(team.current_median_record.get_points_for()), 2):.2f}",
                team.current_median_record.get_streak_str(),
                f"{team.current_median_record.get_points_against():.2f}",
            ]

            current_median_standings_data.append(team_current_median_standings_data)
            rank += 1

        return current_median_standings_data

    @staticmethod
    def get_playoff_probs_data(
        league_standings: List[BaseTeam], data_for_playoff_probs: Dict[str, List[Any]]
    ) -> List[List[Any]]:
        logger.debug("Creating league playoff probabilities data.")

        has_divisions = False
        playoff_probs_data = []
        team: BaseTeam
        for team in league_standings:
            # sum rolling place percentages together to get a cumulative percentage chance of achieving that place
            # summed_stats = []
            # ndx = 1
            team_with_playoff_probs = data_for_playoff_probs[team.team_id]
            team_playoff_stats = team_with_playoff_probs[2]
            # while ndx <= len(team_playoff_stats):
            #     summed_stats.append(sum(team_playoff_stats[:ndx]))
            #     ndx += 1
            # if summed_stats[-1] > 100.00:
            #     summed_stats[-1] = 100.00
            if team_playoff_stats[-1] > 100.00:
                team_playoff_stats[-1] = 100.00

            team_playoffs_data = [
                team_with_playoff_probs[0],
                team.manager_str,
                str(team.record.get_wins())
                + "-"
                + str(team.record.get_losses())
                + "-"
                + str(team.record.get_ties())
                + " ("
                + str(team.record.get_percentage())
                + ")",
                team_with_playoff_probs[1],
                team_with_playoff_probs[3],
            ] + team_playoff_stats
            # ] + summed_stats

            if team.record.division or team.record.division == 0:
                has_divisions = True
                team_playoffs_data.insert(
                    3,
                    str(team.record.get_division_wins())
                    + "-"
                    + str(team.record.get_division_losses())
                    + "-"
                    + str(team.record.get_division_ties())
                    + " ("
                    + str(team.record.get_division_percentage())
                    + ")",
                )

            # add value for if team was predicted division winner to pass to the later sort function
            team_playoffs_data.append(team_with_playoff_probs[4])

            # add value for if team was predicted division qualifier to pass to the later sort function
            team_playoffs_data.append(team_with_playoff_probs[5])

            playoff_probs_data.append(team_playoffs_data)

        prob_ndx = 3
        if has_divisions:
            prob_ndx = 4

        sorted_playoff_probs_data = sorted(playoff_probs_data, key=lambda x: (x[-2], x[-1], x[prob_ndx]), reverse=True)
        for team_playoff_probs_data in sorted_playoff_probs_data:
            team_playoff_probs_data.pop(-1)  # remove "division qualifier" bool (original index: -1)
            team_playoff_probs_data.pop(-1)  # remove "division winner" bool (original index: -2)
            team_playoff_probs_data[prob_ndx] = f"{team_playoff_probs_data[prob_ndx]:.2f}%"
            if team_playoff_probs_data[prob_ndx + 1] == 1:
                team_playoff_probs_data[prob_ndx + 1] = f"{int(float(team_playoff_probs_data[prob_ndx + 1]))} win"
            else:
                team_playoff_probs_data[prob_ndx + 1] = f"{int(float(team_playoff_probs_data[prob_ndx + 1]))} wins"
            ndx = prob_ndx + 2
            for stat in team_playoff_probs_data[prob_ndx + 2:]:
                team_playoff_probs_data[ndx] = f"{stat:.2f}%"
                ndx += 1

        return sorted_playoff_probs_data

    @staticmethod
    def get_score_data(score_results: List[BaseTeam]) -> List[TeamMetricResult]:
        logger.debug("Creating league score data.")

        score_results_data = []
        place = 1
        team: BaseTeam
        for team in score_results:
            score_results_data.append(
                TeamMetricResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    value=f"{team.points:.2f}"
                )
            )
            place += 1

        return score_results_data

    def get_coaching_efficiency_data(self, coaching_efficiency_results: List[BaseTeam]) -> List[TeamMetricResult]:
        logger.debug("Creating league coaching efficiency data.")

        coaching_efficiency_results_data = []
        place = 1
        team: BaseTeam
        for team in coaching_efficiency_results:
            ranked_coaching_efficiency = team.coaching_efficiency

            if ranked_coaching_efficiency == "DQ":
                self.coaching_efficiency_dq_count += 1
                value = "DQ"
            else:
                value = f"{ranked_coaching_efficiency:.2f}%"

            coaching_efficiency_results_data.append(
                TeamMetricResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    value=value
                )
            )

            place += 1

        return coaching_efficiency_results_data

    @staticmethod
    def get_luck_data(luck_results: List[BaseTeam]) -> List[TeamMetricResult]:
        logger.debug("Creating league luck data.")

        luck_results_data = []
        place = 1
        team: BaseTeam
        for team in luck_results:
            luck_results_data.append(
                TeamMetricResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    value=f"{team.luck:.2f}%"
                )
            )
            place += 1
        return luck_results_data

    @staticmethod
    def get_optimal_score_data(score_results: List[BaseTeam]) -> List[TeamMetricResult]:
        logger.debug("Creating league optimal score data.")

        optimal_score_results_data = []
        place = 1
        team: BaseTeam
        for team in score_results:
            optimal_score_results_data.append(
                TeamMetricResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    value=f"{team.optimal_points:.2f}"
                )
            )
            place += 1

        return optimal_score_results_data

    @staticmethod
    def get_bad_boy_data(bad_boy_results: List[BaseTeam]) -> List[BadBoyResult]:
        logger.debug("Creating league bad boys data.")

        bad_boy_results_data = []
        place = 1
        team: BaseTeam
        for team in bad_boy_results:
            bad_boy_results_data.append(
                BadBoyResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    points=team.bad_boy_points,
                    worst_offense=team.worst_offense,
                    num_offenders=team.num_offenders
                )
            )
            place += 1
        return bad_boy_results_data

    @staticmethod
    def get_beef_rank_data(beef_results: List[BaseTeam]) -> List[BeefResult]:
        logger.debug("Creating league beef data.")

        beef_results_data = []
        place = 1
        team: BaseTeam
        for team in beef_results:
            beef_results_data.append(
                BeefResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    tabbu=team.tabbu
                )
            )
            place += 1
        return beef_results_data

    @staticmethod
    def get_high_roller_data(high_roller_results: List[BaseTeam]) -> List[HighRollerResult]:
        logger.debug("Creating league high roller data.")

        high_roller_results_data = []
        place = 1
        team: BaseTeam
        for team in high_roller_results:
            high_roller_results_data.append(
                HighRollerResult(
                    rank=place,
                    team_name=team.name,
                    manager=team.manager_str,
                    fines_total=team.fines_total,
                    worst_violation=team.worst_violation,
                    worst_violation_fine=team.worst_violation_fine
                )
            )
            place += 1
        return high_roller_results_data

    @staticmethod
    def _get_metric_value(x: Any) -> Any:
        if isinstance(x, list):
            return x[3] if len(x) > 3 else None
        if hasattr(x, 'value'): return x.value
        if hasattr(x, 'points'): return x.points
        if hasattr(x, 'fines_total'): return x.fines_total
        if hasattr(x, 'tabbu'): return x.tabbu
        return None

    def get_ties_count(self, results_data: List[Any], tie_type: str, break_ties: bool) -> int:
        def get_val(x):
            return self._get_metric_value(x)

        if tie_type == "power_ranking":
            key_func = lambda x: x.rank if hasattr(x, 'rank') else (x[0] if isinstance(x, list) else None)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = self.count_ties(groups)
        elif tie_type == "bad_boy":
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = self.count_ties(groups)
        elif tie_type == "high_roller":
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = self.count_ties(groups)
        elif tie_type == "beef":
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = self.count_ties(groups)
        else:
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = self.count_ties(groups)

        # if there are ties, record them and break them if possible
        if num_ties > 0:
            ties_count = 0
            team_index = 0
            place = 1
            while ties_count != num_ties:
                for group in groups:
                    first_elem = group[0]
                    val = get_val(first_elem)
                    group_has_ties = len(group) > 1 and val != "DQ"
                    if group_has_ties:
                        ties_count += sum(range(len(group)))

                    for team in group:
                        if tie_type == "power_ranking":
                            rank_val = team.rank if hasattr(team, 'rank') else (team[0] if isinstance(team, list) else None)
                            name_val = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
                            mgr_val = team.manager if hasattr(team, 'manager') else (team[2] if isinstance(team, list) else None)
                            results_data[team_index] = [
                                str(rank_val) + ("*" if group_has_ties else ""),
                                name_val,
                                mgr_val,
                            ]
                        elif tie_type == "score" and break_ties:
                            rank_val = place
                            name_val = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
                            mgr_val = team.manager if hasattr(team, 'manager') else (team[2] if isinstance(team, list) else None)
                            val_val = get_val(team)
                            results_data[team_index] = [str(rank_val), name_val, mgr_val, val_val]
                            if group.index(team) != (len(group) - 1):
                                place += 1
                        elif tie_type == "bad_boy":
                            rank_val = place
                            name_val = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
                            mgr_val = team.manager if hasattr(team, 'manager') else (team[2] if isinstance(team, list) else None)
                            val_val = get_val(team)
                            worst_off = team.worst_offense if hasattr(team, 'worst_offense') else (team[4] if isinstance(team, list) else None)
                            num_off = team.num_offenders if hasattr(team, 'num_offenders') else (team[5] if isinstance(team, list) else None)
                            results_data[team_index] = [
                                str(rank_val) + ("*" if group_has_ties else ""),
                                name_val,
                                mgr_val,
                                val_val,
                                worst_off,
                                num_off,
                            ]
                        elif tie_type == "high_roller":
                            rank_val = place
                            name_val = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
                            mgr_val = team.manager if hasattr(team, 'manager') else (team[2] if isinstance(team, list) else None)
                            val_val = get_val(team)
                            worst_vio = team.worst_violation if hasattr(team, 'worst_violation') else (team[4] if isinstance(team, list) else None)
                            worst_fine = team.worst_violation_fine if hasattr(team, 'worst_violation_fine') else (team[5] if isinstance(team, list) else None)
                            results_data[team_index] = [
                                str(rank_val) + ("*" if group_has_ties else ""),
                                name_val,
                                mgr_val,
                                val_val,
                                worst_vio,
                                worst_fine,
                            ]
                        else:
                            rank_val = place
                            name_val = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
                            mgr_val = team.manager if hasattr(team, 'manager') else (team[2] if isinstance(team, list) else None)
                            val_val = get_val(team)
                            results_data[team_index] = [
                                str(rank_val) + ("*" if group_has_ties else ""),
                                name_val,
                                mgr_val,
                                val_val,
                            ]

                        if tie_type == "score":
                            if not hasattr(team, 'rank'): # it's a list
                                results_data[team_index].append(team[4] if len(team) > 4 else None)
                            else:
                                results_data[team_index].append(None)

                        team_index += 1
                    place += 1

        if tie_type == "bad_boy":
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = 0
            for group in groups:
                first_elem = group[0]
                val = get_val(first_elem)
                if len(group) > 1 and (val is not None and float(val) > 0):
                    num_ties += sum(range(len(group)))

        if tie_type == "high_roller":
            key_func = lambda x: get_val(x)
            groups = [list(group) for key, group in itertools.groupby(results_data, key_func)]
            num_ties = 0
            for group in groups:
                first_elem = group[0]
                val = get_val(first_elem)
                if len(group) > 1 and (val is not None and float(val) > 0):
                    num_ties += sum(range(len(group)))

        return num_ties

    @staticmethod
    def count_ties(groups: List[List[Any]]) -> int:
        num_ties = 0
        for group in groups:
            first_elem = group[0]
            val = CalculateMetrics._get_metric_value(first_elem)
            if len(group) > 1 and val != "DQ":
                num_ties += sum(range(len(group)))

        return num_ties

    @staticmethod
    def resolve_score_ties(data_for_scores: List[Any], break_ties: bool) -> List[List[Any]]:
        # Convert dataclasses to lists to allow for modification and additional columns
        converted_data = []
        for item in data_for_scores:
            if hasattr(item, 'rank'):
                converted_data.append([item.rank, item.team_name, item.manager, item.value])
            else:
                converted_data.append(list(item))

        groups = [list(group) for key, group in itertools.groupby(converted_data, lambda x: x[3])]

        resolved_score_results_data = []
        place = 1
        for group in groups:
            # Tie-break based on bench points (assumed to be at index 4 if it exists)
            sorted_group = sorted(group, key=lambda x: (x[4] if len(x) > 4 and x[4] is not None else 0), reverse=True)
            for team in sorted_group:
                if groups.index(group) != 0:
                    team[0] = place
                else:
                    if break_ties:
                        team[0] = place
                resolved_score_results_data.append(team)
                place += 1

        return resolved_score_results_data

    @staticmethod
    def resolve_coaching_efficiency_ties(
        data_for_coaching_efficiency: List[Any],
        ties_for_coaching_efficiency: int,
        league: BaseLeague,
        teams_results: Dict[str, BaseTeam],
        week: int,
        week_for_report: int,
        break_ties: bool,
    ) -> List[List[Any]]:
        logger.debug("Resolving coaching efficiency ties.")

        # Convert dataclasses to lists
        converted_data = []
        for item in data_for_coaching_efficiency:
            if hasattr(item, 'rank'):
                converted_data.append([item.rank, item.team_name, item.manager, item.value])
            else:
                converted_data.append(list(item))

        coaching_efficiency_results_data_with_tiebreakers = []
        bench_positions = league.bench_positions

        season_average_points_by_player_dict = defaultdict(list)
        if break_ties and ties_for_coaching_efficiency > 0 and week == int(week_for_report):
            for ce_result in converted_data:
                if ce_result[0] == "1*":
                    players = []
                    for team_result in teams_results.values():
                        if team_result.name == ce_result[1]:
                            team_obj = teams_results.get(team_result.team_id)
                            # roster can be None on some platforms / edge cases
                            players = (team_obj.roster if team_obj is not None else None) or []
                            break

                    num_players_exceeded_season_avg_points = 0
                    total_percentage_points_players_exceeded_season_avg_points = 0
                    player: BasePlayer
                    bench_pos = bench_positions or []
                    for player in players:
                        if player.selected_position not in bench_pos:
                            week_counter = 1
                            while week_counter <= int(week):
                                players_by_week = league.players_by_week.get(str(week_counter)) or {}
                                if str(player.player_id) in players_by_week:
                                    season_average_points_by_player_dict[player.player_id].append(
                                        players_by_week[str(player.player_id)].points
                                    )

                                week_counter += 1

                            player_last_week_points = season_average_points_by_player_dict[player.player_id][-1]

                            # handle the beginning of the season when a player has only played one or no games
                            player_season_weekly_points = season_average_points_by_player_dict[player.player_id]
                            if len(player_season_weekly_points) == 0:
                                player_season_avg_points = 0
                            elif len(player_season_weekly_points) == 1:
                                player_season_avg_points = player_season_weekly_points[0]
                            else:
                                player_season_avg_points = mean(player_season_weekly_points[:-1])

                            if player_last_week_points > player_season_avg_points:
                                num_players_exceeded_season_avg_points += 1

                                if player_season_avg_points > 0:
                                    total_percentage_points_players_exceeded_season_avg_points += (
                                        (player_last_week_points - player_season_avg_points) / player_season_avg_points
                                    ) * 100.0
                                else:
                                    total_percentage_points_players_exceeded_season_avg_points += 100.0

                    ce_result.extend(
                        [
                            num_players_exceeded_season_avg_points,
                            round(total_percentage_points_players_exceeded_season_avg_points, 2),
                        ]
                    )
                    coaching_efficiency_results_data_with_tiebreakers.append(ce_result)
                else:
                    ce_result.extend(["N/A", "N/A"])
                    coaching_efficiency_results_data_with_tiebreakers.append(ce_result)

            groups = [
                list(group)
                for key, group in itertools.groupby(coaching_efficiency_results_data_with_tiebreakers, lambda x: x[3])
            ]
        else:
            groups = [list(group) for key, group in itertools.groupby(converted_data, lambda x: x[3])]

        resolved_coaching_efficiency_results_data = []
        place = 1
        for group in groups:
            for team in sorted(group, key=lambda x: (x[-2] if x[-2] != "DQ" else 0, x[-1]), reverse=True):
                if groups.index(group) == 0:
                    if break_ties:
                        team[0] = place
                resolved_coaching_efficiency_results_data.append(team)
                place += 1
        return resolved_coaching_efficiency_results_data

    @staticmethod
    def resolve_season_average_ties(data_for_season_averages: List[Any], with_percent: bool) -> List[List[Any]]:
        # Convert dataclasses to lists
        converted_data = []
        for item in data_for_season_averages:
            if hasattr(item, 'rank'):
                converted_data.append([item.rank, item.team_name, item.manager, item.value])
            else:
                converted_data.append(list(item))

        groups = [list(group) for key, group in itertools.groupby(converted_data, lambda x: x[2])]

        resolved_season_average_results_data = []
        place = 1
        for group in groups:
            for team in sorted(group, key=lambda x: x[-1], reverse=True):
                team[0] = place
                if with_percent:
                    team[2] = f"{team[2]}% ({place})"
                else:
                    team[2] = f"{team[2]} ({place})"

                resolved_season_average_results_data.append(team)
            place += 1

        return resolved_season_average_results_data

    # noinspection PyUnusedLocal
    @staticmethod
    def test_ties(teams_results):
        for team_id, team in teams_results.items():
            team_id = team.team_id

            # for testing score ties
            test_score = 70
            test_efficiency = 75.00
            test_luck = 10.00
            test_power_rank = 5.0

            # swap the first team to test for non-first place ties vs. first place ties
            # if int(team_id) == 1:
            #     test_score = 101
            #     test_efficiency = 101.00
            #     test_luck = 99.50
            #     test_power_rank = 0.9
            if int(team_id) == 1:
                test_score = 100
                test_efficiency = 100.00
                test_luck = 99.00
                test_power_rank = 1.0
            elif int(team_id) == 2:
                test_score = 100
                test_efficiency = 100.00
                test_luck = 99.00
                test_power_rank = 1.0
            # swap the third time to test for middle ranked non-ties
            # elif int(team_id) == 3:
            #     test_score = 100
            #     test_efficiency = 100.00
            #     test_luck = 99.00
            #     test_power_rank = 1.0
            elif int(team_id) == 3:
                test_score = 95
                test_efficiency = 95.00
                test_luck = 50.00
                test_power_rank = 1.5
            elif int(team_id) == 4:
                test_score = 90
                test_efficiency = 90.00
                test_luck = 5.00
                test_power_rank = 2.0
            elif int(team_id) == 5:
                test_score = 90
                test_efficiency = 90.00
                test_luck = 5.00
                test_power_rank = 2.0
            elif int(team_id) == 6:
                test_score = 90
                test_efficiency = 90.00
                test_luck = 5.00
                test_power_rank = 2.0
            # uncomment to test ending teams with unique place
            elif int(team_id) == len(list(teams_results.keys())):
                test_score = 85  # noqa: F841
                test_efficiency = 85.00  # noqa: F841
                test_luck = -5.00  # noqa: F841
                test_power_rank = 6.0  # noqa: F841

            # # uncomment to test scoring ties
            # team.score = test_score
            #
            # # uncomment to test coaching efficiency ties
            # team.coaching_efficiency = test_efficiency
            #
            # # # uncomment to test luck ties
            # team.luck = test_luck
            #
            # # # uncomment to test power ranking ties
            # team.power_rank = test_power_rank

    @staticmethod
    def calculate_records(
        week: int, league: BaseLeague, custom_weekly_matchups: List[Dict[str, Dict[str, Any]]]
    ) -> Dict[str, BaseRecord]:
        logger.debug(f'Calculating league records for week "{week}".')

        standings = league.standings if league.standings else league.current_standings

        records = defaultdict(BaseRecord)
        team: BaseTeam
        for team in standings:
            if week == league.start_week:
                record = BaseRecord(week, team_id=team.team_id, team_name=team.name, division=team.division)
            else:
                previous_week_record: BaseRecord = league.records_by_week[str(week - 1)][team.team_id]
                record = BaseRecord(
                    week,
                    wins=previous_week_record.get_wins(),
                    ties=previous_week_record.get_ties(),
                    losses=previous_week_record.get_losses(),
                    points_for=previous_week_record.get_points_for(),
                    points_against=previous_week_record.get_points_against(),
                    streak_type=previous_week_record.get_streak_type(),
                    streak_len=previous_week_record.get_streak_length(),
                    team_id=team.team_id,
                    team_name=team.name,
                    division=team.division,
                    division_wins=previous_week_record.get_division_wins(),
                    division_ties=previous_week_record.get_division_ties(),
                    division_losses=previous_week_record.get_division_losses(),
                    division_points_for=previous_week_record.get_division_points_for(),
                    division_points_against=previous_week_record.get_division_points_against(),
                    division_streak_type=previous_week_record.get_division_streak_type(),
                    division_streak_len=previous_week_record.get_division_streak_length(),
                )

            # league.matchups_by_week[str(week)]

            for matchup in custom_weekly_matchups:
                for team_id, matchup_result in matchup.items():
                    if str(team_id) == str(team.team_id):
                        outcome = matchup_result["result"]
                        if outcome == "W":
                            record.add_win()
                            if matchup_result["division"]:
                                record.add_division_win()
                        elif outcome == "L":
                            record.add_loss()
                            if matchup_result["division"]:
                                record.add_division_loss()
                        else:
                            record.add_tie()
                            if matchup_result["division"]:
                                record.add_division_tie()
                        record.add_points_for(matchup_result["points_for"])
                        record.add_points_against(matchup_result["points_against"])
                        if matchup_result["division"]:
                            record.add_division_points_for(matchup_result["points_for"])
                            record.add_division_points_against(matchup_result["points_against"])
                        records[team.team_id] = record

            team.record = record

        ordered_records = OrderedDict()
        standings_rank = 1
        for ordered_record in sorted(
            records.items(),
            key=lambda x: (-x[1].get_wins(), -x[1].get_losses(), -x[1].get_ties(), -x[1].get_points_for()),
        ):
            ordered_record[1].rank = standings_rank
            ordered_records[ordered_record[0]] = ordered_record[1]
            standings_rank += 1

        league.records_by_week[str(week)] = ordered_records
        return records

    @staticmethod
    def calculate_luck(
        week: int, league: BaseLeague, custom_weekly_matchups: List[Dict[str, Dict[str, Any]]]
    ) -> Dict[str, Dict[str, BaseRecord]]:
        logger.debug(f'Calculating luck for week "{week}".')

        luck_results = defaultdict(defaultdict)

        teams = league.teams_by_week.get(str(week))

        # Handle weeks with no teams (e.g., playoff weeks where not all teams play)
        if not teams:
            logger.debug(f"No teams found for week {week}, skipping luck calculation")
            return luck_results

        matchups = {
            str(team_id): value["result"] for pair in custom_weekly_matchups for team_id, value in list(pair.items())
        }

        team_1: BaseTeam
        for team_1 in teams.values():
            luck_record = BaseRecord()

            for team_2 in teams.values():
                if team_1.team_id == team_2.team_id:
                    continue
                score_1 = team_1.points
                score_2 = team_2.points

                if float(score_1) > float(score_2):
                    luck_record.add_win()
                elif float(score_1) < float(score_2):
                    luck_record.add_loss()
                else:
                    luck_record.add_tie()

            luck_results[team_1.team_id]["luck_record"] = luck_record

            # calc luck %
            # TODO: assuming no ties...  how are tiebreakers handled?
            luck = 0.0
            # number of teams excluding current team
            num_teams = float(len(teams)) - 1

            if luck_record.get_wins() != 0 and luck_record.get_losses() != 0:
                matchup_result = matchups[str(team_1.team_id)]
                if matchup_result == "W" or matchup_result == "T":
                    luck = (luck_record.get_losses() + luck_record.get_ties()) / num_teams
                else:
                    luck = 0 - (luck_record.get_wins() + luck_record.get_ties()) / num_teams

            # noinspection PyTypeChecker
            luck_results[team_1.team_id]["luck"] = luck * 100

        return luck_results

    @staticmethod
    def get_ranks_for_metric(
        data_for_metric: List[Any], power_ranked_teams: Dict[str, Dict[str, Any]], metric_ranking_key: str
    ):
        rank = 1
        for team in data_for_metric:
            team_name = team.team_name if hasattr(team, 'team_name') else (team[1] if isinstance(team, list) else None)
            for team_rankings in power_ranked_teams.values():
                if team_name == team_rankings["name"]:
                    team_rankings[metric_ranking_key] = rank
            rank += 1

    def calculate_power_rankings(
        self,
        teams_results: Dict[str, BaseTeam],
        data_for_scores: List[Any],
        data_for_coaching_efficiency: List[Any],
        data_for_luck: List[Any],
    ) -> Dict[str, Dict[str, Any]]:
        """avg of (weekly score rank + weekly coaching efficiency rank + weekly luck rank)"""
        logger.debug("Calculating power rankings.")

        power_ranked_teams = {
            team_result.team_id: {"name": team_result.name, "manager_str": team_result.manager_str}
            for team_result in teams_results.values()
        }

        self.get_ranks_for_metric(data_for_scores, power_ranked_teams, "score_ranking")
        self.get_ranks_for_metric(data_for_coaching_efficiency, power_ranked_teams, "coaching_efficiency_ranking")
        self.get_ranks_for_metric(data_for_luck, power_ranked_teams, "luck_ranking")

        for team_rankings in power_ranked_teams.values():
            # noinspection PyTypeChecker
            team_rankings["power_ranking"] = (
                team_rankings["score_ranking"]
                + team_rankings["coaching_efficiency_ranking"]
                + team_rankings["luck_ranking"]
            ) // 3.0
        return power_ranked_teams

    @staticmethod
    def calculate_z_scores(weekly_teams_results: List[Dict[str, BaseTeam]]) -> Dict[str, float]:
        logger.debug("Calculating z-scores.")

        results = {}

        # can only determine z_score
        can_calculate = len(weekly_teams_results) > 2

        # iterates through team ids of first week since team ids remain unchanged
        for team_id in weekly_teams_results[0].keys():
            z_score = None

            if can_calculate:
                # Check if team exists in all weeks before calculating z-score
                if not all(team_id in week for week in weekly_teams_results):
                    logger.debug(f"Team {team_id} not found in all weeks, skipping z-score calculation")
                    results[team_id] = None
                    continue

                scores = [week[team_id].points for week in weekly_teams_results]

                scores_excluding_current = scores[:-1]
                current_score = scores[-1]

                standard_deviation = np.std(scores_excluding_current)
                mean_score = np.mean(scores_excluding_current)
                z_score = (
                    (float(current_score) - float(mean_score)) / float(standard_deviation)
                    if standard_deviation != 0
                    else 0
                )

            results[team_id] = z_score

        return results
