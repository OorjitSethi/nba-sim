from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nba_sim.domain.enums import PossessionEnd, ShotZone
from nba_sim.domain.events import EventType
from nba_sim.domain.profiles import PlayerProfile, TeamProfile
from nba_sim.epv.model import (
    CompetingRiskEPVModel,
    PossessionContext,
    TerminalAction,
)
from nba_sim.simulation.emitter import EventEmitter
from nba_sim.spatial.interfaces import TrajectoryModel
from nba_sim.spatial.state import (
    SpatialSummary,
    initial_half_court_frame,
)


@dataclass(frozen=True)
class PossessionResult:
    elapsed_ms: int
    end: PossessionEnd
    offensive_rebounds: int


class PossessionSimulator:
    def __init__(
        self,
        *,
        epv_model: CompetingRiskEPVModel | None = None,
        trajectory_model: TrajectoryModel | None = None,
    ) -> None:
        self.epv_model = epv_model or CompetingRiskEPVModel()
        self.trajectory_model = trajectory_model

    def simulate(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        rng: np.random.Generator,
    ) -> PossessionResult:
        start_clock = emitter.state.period_clock_ms
        handler = self._weighted_player(
            offense_lineup,
            [
                player.usage_rate
                * (1.15 if "G" in player.position.upper() else 1.0)
                for player in offense_lineup
            ],
            rng,
        )
        offensive_rebounds = 0
        transition_opportunity = emitter.state.transition_opportunity

        for cycle in range(17):
            if emitter.state.period_clock_ms <= 0:
                return PossessionResult(
                    start_clock - emitter.state.period_clock_ms,
                    PossessionEnd.PERIOD_END,
                    offensive_rebounds,
                )

            spatial = self._spatial_summary(
                handler=handler,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                emitter=emitter,
                rng=rng,
            )
            context = PossessionContext(
                offense=offense_lineup,
                defense=defense_lineup,
                ball_handler=handler,
                period=emitter.state.period,
                period_clock_seconds=emitter.state.period_clock_ms / 1_000.0,
                shot_clock_seconds=emitter.state.shot_clock_ms / 1_000.0,
                score_margin=self._score_margin(emitter, offense.abbreviation),
                offense_is_home=offense.abbreviation == emitter.state.home_team,
                spatial=spatial,
                target_pace=(offense.pace + defense.pace) / 2.0,
                transition=transition_opportunity and cycle == 0,
            )
            action = self.epv_model.sample_terminal_action(context, rng)
            initial_shot_clock = emitter.state.shot_clock_ms
            emitter.advance_clock(action.elapsed_seconds)

            if action.action is TerminalAction.PERIOD_END:
                return PossessionResult(
                    start_clock - emitter.state.period_clock_ms,
                    PossessionEnd.PERIOD_END,
                    offensive_rebounds,
                )

            if action.action is TerminalAction.TURNOVER:
                violation = (
                    initial_shot_clock > 0
                    and emitter.state.shot_clock_ms == 0
                    and action.elapsed_seconds * 1_000 >= initial_shot_clock - 1
                )
                self._turnover(
                    emitter=emitter,
                    offense=offense,
                    defense=defense,
                    handler=handler,
                    defense_lineup=defense_lineup,
                    rng=rng,
                    violation=violation,
                )
                return PossessionResult(
                    start_clock - emitter.state.period_clock_ms,
                    PossessionEnd.TURNOVER,
                    offensive_rebounds,
                )

            if action.action is TerminalAction.DEFENSIVE_FOUL:
                foul_resolution = self._common_defensive_foul(
                    emitter=emitter,
                    offense=offense,
                    defense=defense,
                    offense_lineup=offense_lineup,
                    defense_lineup=defense_lineup,
                    handler=handler,
                    rng=rng,
                    force_defensive_rebound=cycle == 16,
                )
                if foul_resolution == "continue":
                    continue
                if foul_resolution == "offensive_rebound":
                    offensive_rebounds += 1
                    handler = self._last_offensive_rebounder(
                        emitter,
                        offense_lineup,
                    )
                    continue
                return PossessionResult(
                    start_clock - emitter.state.period_clock_ms,
                    PossessionEnd.DEFENSIVE_REBOUND,
                    offensive_rebounds,
                )

            point_value = (
                3 if action.action is TerminalAction.THREE_POINT_ATTEMPT else 2
            )
            shooter, zone = self._select_shooter_and_zone(
                offense_lineup,
                point_value,
                rng,
            )
            defender = self._match_defender(shooter, defense_lineup)
            resolution = self._resolve_shot(
                emitter=emitter,
                offense=offense,
                defense=defense,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                handler=handler,
                shooter=shooter,
                defender=defender,
                zone=zone,
                spatial=spatial,
                rng=rng,
                force_defensive_rebound=cycle == 16,
                transition=transition_opportunity and cycle == 0,
            )
            if resolution == "offensive_rebound":
                offensive_rebounds += 1
                handler = self._last_offensive_rebounder(
                    emitter,
                    offense_lineup,
                )
                continue
            if resolution == "period_end":
                end = PossessionEnd.PERIOD_END
            elif resolution == "made":
                end = PossessionEnd.MADE_SHOT
            else:
                end = PossessionEnd.DEFENSIVE_REBOUND
            return PossessionResult(
                start_clock - emitter.state.period_clock_ms,
                end,
                offensive_rebounds,
            )

        raise RuntimeError("possession cycle limit was not resolved")

    def _spatial_summary(
        self,
        *,
        handler: PlayerProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        emitter: EventEmitter,
        rng: np.random.Generator,
    ) -> SpatialSummary:
        frame = initial_half_court_frame(
            offense=offense_lineup,
            defense=defense_lineup,
            possession_team=handler.team_abbreviation,
            game_clock_seconds=emitter.state.period_clock_ms / 1_000.0,
            shot_clock_seconds=emitter.state.shot_clock_ms / 1_000.0,
            ball_handler_id=handler.player_id,
        )
        if self.trajectory_model is not None:
            rollout = self.trajectory_model.rollout(
                frame,
                steps=5,
                step_seconds=0.2,
                rng=rng,
            )
            frame = rollout.frames[-1]
        return SpatialSummary.from_frame(frame)

    def _turnover(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        handler: PlayerProfile,
        defense_lineup: tuple[PlayerProfile, ...],
        rng: np.random.Generator,
        violation: bool,
    ) -> None:
        is_steal = not violation and rng.random() < 0.595
        emitter.emit(
            EventType.TURNOVER,
            team=offense.abbreviation,
            player_id=handler.player_id,
            payload={
                "turnover_type": (
                    "shot_clock_violation"
                    if violation
                    else ("live_ball" if is_steal else "dead_ball")
                )
            },
        )
        if is_steal:
            stealer = self._weighted_player(
                defense_lineup,
                [player.steal_share for player in defense_lineup],
                rng,
            )
            emitter.emit(
                EventType.STEAL,
                team=defense.abbreviation,
                player_id=stealer.player_id,
                related_player_id=handler.player_id,
            )
        emitter.emit(
            EventType.POSSESSION_CHANGED,
            team=defense.abbreviation,
            payload={"transition": is_steal},
        )

    def _common_defensive_foul(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        handler: PlayerProfile,
        rng: np.random.Generator,
        force_defensive_rebound: bool,
    ) -> str:
        defender = self._weighted_player(
            defense_lineup,
            [max(0.1, 1.0 - player.defensive_impact) for player in defense_lineup],
            rng,
        )
        emitter.emit(
            EventType.FOUL,
            team=defense.abbreviation,
            player_id=defender.player_id,
            related_player_id=handler.player_id,
            payload={
                "foul_type": (
                    "intentional"
                    if (
                        emitter.state.period >= 4
                        and emitter.state.period_clock_ms <= 45_000
                        and 0 < self._score_margin(
                            emitter,
                            offense.abbreviation,
                        )
                        <= 8
                    )
                    else "common"
                ),
                "reset_shot_clock_ms": emitter.rules.offensive_rebound_shot_clock_ms,
            },
        )
        penalty = emitter.rules.in_team_foul_penalty(
            period=emitter.state.period,
            period_clock_ms=emitter.state.period_clock_ms,
            team_fouls_after_foul=emitter.state.team_fouls[defense.abbreviation],
            last_two_minute_fouls_after_foul=emitter.state.last_two_minute_fouls[
                defense.abbreviation
            ],
        )
        if not penalty:
            return "continue"
        retained = self._shoot_free_throws(
            emitter=emitter,
            offense=offense,
            defense=defense,
            offense_lineup=offense_lineup,
            defense_lineup=defense_lineup,
            shooter=handler,
            attempts=2,
            rng=rng,
            force_defensive_rebound=force_defensive_rebound,
        )
        return "offensive_rebound" if retained else "defensive_rebound"

    def _resolve_shot(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        handler: PlayerProfile,
        shooter: PlayerProfile,
        defender: PlayerProfile,
        zone: ShotZone,
        spatial: SpatialSummary,
        rng: np.random.Generator,
        force_defensive_rebound: bool,
        transition: bool,
    ) -> str:
        point_value = zone.point_value
        base_make = shooter.make_probability(zone)
        defense_penalty = 0.22 * defender.defensive_impact
        contest_penalty = max(0.0, 4.5 - spatial.closest_defender_ft) * 0.006
        home_adjustment = 0.006 if offense.abbreviation == emitter.state.home_team else -0.006
        transition_adjustment = 0.025 if transition else 0.0
        make_probability = float(
            np.clip(
                base_make
                - defense_penalty
                - contest_penalty
                + home_adjustment
                + transition_adjustment,
                0.04,
                0.82,
            )
        )
        # Legacy zone percentages already contain real blocked attempts. The
        # intercept aligns the higher-minute simulated rotation to league shooting
        # before misses are classified as blocks below.
        make_probability = float(np.clip(make_probability - 0.016, 0.04, 0.82))
        if point_value == 3:
            make_probability = float(
                np.clip(make_probability - 0.010, 0.04, 0.82)
            )
        shooting_foul_probability = float(
            np.clip(
                0.90
                * (
                    shooter.shooting_foul_probability
                    - max(0.0, defender.defensive_impact) * 0.12
                ),
                0.04,
                0.20,
            )
        )
        foul = rng.random() < shooting_foul_probability
        blocker = max(
            defense_lineup,
            key=lambda player: player.block_probability + player.height_inches * 0.0002,
        )
        desired_block_probability = blocker.block_probability * (
            2.72 if point_value == 2 else 0.59
        )
        made = rng.random() < make_probability
        conditional_block_probability = min(
            0.75,
            desired_block_probability / max(1.0 - make_probability, 0.05),
        )
        blocked = (
            not foul
            and not made
            and rng.random() < conditional_block_probability
        )

        emitter.emit(
            EventType.SHOT_ATTEMPT,
            team=offense.abbreviation,
            player_id=shooter.player_id,
            related_player_id=defender.player_id,
            payload={
                "zone": zone.value,
                "point_value": point_value,
                "counts_as_fga": bool(made or not foul),
                "make_probability": round(make_probability, 6),
                "closest_defender_ft": round(spatial.closest_defender_ft, 3),
            },
        )
        if blocked:
            emitter.emit(
                EventType.BLOCK,
                team=defense.abbreviation,
                player_id=blocker.player_id,
                related_player_id=shooter.player_id,
            )

        if foul:
            emitter.emit(
                EventType.FOUL,
                team=defense.abbreviation,
                player_id=defender.player_id,
                related_player_id=shooter.player_id,
                payload={"foul_type": "shooting"},
            )

        if made:
            emitter.emit(
                EventType.SHOT_MADE,
                team=offense.abbreviation,
                player_id=shooter.player_id,
                related_player_id=defender.player_id,
                points=point_value,
                payload={"zone": zone.value},
            )
            self._maybe_assist(
                emitter=emitter,
                offense=offense,
                lineup=offense_lineup,
                handler=handler,
                shooter=shooter,
                point_value=point_value,
                rng=rng,
            )
            if foul:
                retained = self._shoot_free_throws(
                    emitter=emitter,
                    offense=offense,
                    defense=defense,
                    offense_lineup=offense_lineup,
                    defense_lineup=defense_lineup,
                    shooter=shooter,
                    attempts=1,
                    rng=rng,
                    force_defensive_rebound=force_defensive_rebound,
                )
                if retained:
                    return "offensive_rebound"
            else:
                emitter.emit(
                    EventType.POSSESSION_CHANGED,
                    team=defense.abbreviation,
                )
            return "made"

        emitter.emit(
            EventType.SHOT_MISSED,
            team=offense.abbreviation,
            player_id=shooter.player_id,
            related_player_id=defender.player_id,
            payload={"zone": zone.value, "blocked": blocked},
        )
        if foul:
            retained = self._shoot_free_throws(
                emitter=emitter,
                offense=offense,
                defense=defense,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                shooter=shooter,
                attempts=point_value,
                rng=rng,
                force_defensive_rebound=force_defensive_rebound,
            )
            return "offensive_rebound" if retained else "defensive_rebound"

        rebound = self._rebound(
            emitter=emitter,
            offense=offense,
            defense=defense,
            offense_lineup=offense_lineup,
            defense_lineup=defense_lineup,
            rng=rng,
            free_throw=False,
            force_defensive=force_defensive_rebound,
        )
        return rebound

    def _shoot_free_throws(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        shooter: PlayerProfile,
        attempts: int,
        rng: np.random.Generator,
        force_defensive_rebound: bool,
    ) -> bool:
        final_made = False
        for attempt in range(1, attempts + 1):
            final_made = rng.random() < shooter.free_throw_probability
            emitter.emit(
                (
                    EventType.FREE_THROW_MADE
                    if final_made
                    else EventType.FREE_THROW_MISSED
                ),
                team=offense.abbreviation,
                player_id=shooter.player_id,
                points=1 if final_made else 0,
                payload={"attempt": attempt, "attempts": attempts},
            )

        if final_made:
            emitter.emit(
                EventType.POSSESSION_CHANGED,
                team=defense.abbreviation,
            )
            return False

        rebound = self._rebound(
            emitter=emitter,
            offense=offense,
            defense=defense,
            offense_lineup=offense_lineup,
            defense_lineup=defense_lineup,
            rng=rng,
            free_throw=True,
            force_defensive=force_defensive_rebound,
        )
        return rebound == "offensive_rebound"

    def _rebound(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        defense: TeamProfile,
        offense_lineup: tuple[PlayerProfile, ...],
        defense_lineup: tuple[PlayerProfile, ...],
        rng: np.random.Generator,
        free_throw: bool,
        force_defensive: bool,
    ) -> str:
        if not free_throw:
            emitter.advance_clock(0.85)
            if emitter.state.period_clock_ms <= 0:
                return "period_end"

        offensive_strength = float(
            np.mean([player.offensive_rebound_weight for player in offense_lineup])
        )
        defensive_strength = float(
            np.mean([player.defensive_rebound_weight for player in defense_lineup])
        )
        relative = (
            offensive_strength / max(offensive_strength + defensive_strength, 1e-9)
            - 0.5
        )
        offensive_probability = (
            0.115 if free_throw else float(np.clip(0.245 + relative * 0.55, 0.12, 0.38))
        )
        offensive = not force_defensive and rng.random() < offensive_probability
        if offensive:
            rebounder = self._weighted_player(
                offense_lineup,
                [player.offensive_rebound_weight for player in offense_lineup],
                rng,
            )
            emitter.emit(
                EventType.OFFENSIVE_REBOUND,
                team=offense.abbreviation,
                player_id=rebounder.player_id,
            )
            return "offensive_rebound"

        rebounder = self._weighted_player(
            defense_lineup,
            [player.defensive_rebound_weight for player in defense_lineup],
            rng,
        )
        emitter.emit(
            EventType.DEFENSIVE_REBOUND,
            team=defense.abbreviation,
            player_id=rebounder.player_id,
        )
        emitter.emit(
            EventType.POSSESSION_CHANGED,
            team=defense.abbreviation,
        )
        return "defensive_rebound"

    def _maybe_assist(
        self,
        *,
        emitter: EventEmitter,
        offense: TeamProfile,
        lineup: tuple[PlayerProfile, ...],
        handler: PlayerProfile,
        shooter: PlayerProfile,
        point_value: int,
        rng: np.random.Generator,
    ) -> None:
        candidates = [player for player in lineup if player.player_id != shooter.player_id]
        if not candidates:
            return
        base_probability = 0.73 if point_value == 3 else 0.51
        if handler.player_id != shooter.player_id:
            base_probability += 0.06
        if rng.random() >= min(0.92, base_probability):
            return

        if handler.player_id != shooter.player_id:
            passer = handler
        else:
            passer = self._weighted_player(
                tuple(candidates),
                [player.assist_probability for player in candidates],
                rng,
            )
        emitter.emit(
            EventType.ASSIST,
            team=offense.abbreviation,
            player_id=passer.player_id,
            related_player_id=shooter.player_id,
        )

    @staticmethod
    def _select_shooter_and_zone(
        lineup: tuple[PlayerProfile, ...],
        point_value: int,
        rng: np.random.Generator,
    ) -> tuple[PlayerProfile, ShotZone]:
        eligible: list[tuple[PlayerProfile, list[ShotZone], float]] = []
        for player in lineup:
            zones = [
                zone
                for zone, profile in player.shot_zones.items()
                if zone.point_value == point_value and profile.frequency > 0
            ]
            frequency = sum(player.shot_zones[zone].frequency for zone in zones)
            if zones and frequency > 0:
                eligible.append((player, zones, player.usage_rate * frequency))

        if not eligible:
            player = max(lineup, key=lambda candidate: candidate.usage_rate)
            zone = (
                ShotZone.ABOVE_BREAK_THREE
                if point_value == 3
                else ShotZone.MID_RANGE
            )
            return player, zone

        weights = np.asarray([item[2] for item in eligible], dtype=float)
        weights /= weights.sum()
        player, zones, _ = eligible[int(rng.choice(len(eligible), p=weights))]
        zone_weights = np.asarray(
            [player.shot_zones[zone].frequency for zone in zones],
            dtype=float,
        )
        zone_weights /= zone_weights.sum()
        zone = zones[int(rng.choice(len(zones), p=zone_weights))]
        return player, zone

    @staticmethod
    def _match_defender(
        shooter: PlayerProfile,
        defense_lineup: tuple[PlayerProfile, ...],
    ) -> PlayerProfile:
        shooter_position = shooter.position.upper()

        def cost(defender: PlayerProfile) -> float:
            position_penalty = (
                0.0
                if any(token in defender.position.upper() for token in shooter_position)
                else 5.0
            )
            return abs(defender.height_inches - shooter.height_inches) + position_penalty

        return min(defense_lineup, key=cost)

    @staticmethod
    def _weighted_player(
        players: tuple[PlayerProfile, ...] | list[PlayerProfile],
        weights: list[float],
        rng: np.random.Generator,
    ) -> PlayerProfile:
        probabilities = np.asarray(weights, dtype=float)
        probabilities = np.clip(probabilities, 0.0, None)
        if probabilities.sum() <= 0:
            probabilities = np.ones(len(players), dtype=float)
        probabilities /= probabilities.sum()
        return players[int(rng.choice(len(players), p=probabilities))]

    @staticmethod
    def _score_margin(emitter: EventEmitter, offense: str) -> int:
        if offense == emitter.state.home_team:
            return emitter.state.home_score - emitter.state.away_score
        return emitter.state.away_score - emitter.state.home_score

    @staticmethod
    def _last_offensive_rebounder(
        emitter: EventEmitter,
        lineup: tuple[PlayerProfile, ...],
    ) -> PlayerProfile:
        rebounder_id = emitter.log[-1].player_id
        for player in lineup:
            if player.player_id == rebounder_id:
                return player
        return lineup[0]
