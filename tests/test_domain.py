from __future__ import annotations

import unittest
import pickle

from nba_sim.domain.events import EventType
from nba_sim.domain.rules import NBA_2025_26
from nba_sim.domain.state import GameState
from nba_sim.randomness import RandomStreamFactory
from nba_sim.simulation.emitter import EventEmitter


class RulesetTests(unittest.TestCase):
    def test_period_lengths_and_shot_clocks(self) -> None:
        self.assertEqual(NBA_2025_26.period_length_ms(1), 720_000)
        self.assertEqual(NBA_2025_26.period_length_ms(5), 300_000)
        self.assertEqual(
            NBA_2025_26.shot_clock_after_offensive_rebound(30_000),
            14_000,
        )
        self.assertEqual(
            NBA_2025_26.shot_clock_for_new_possession(8_500),
            8_500,
        )

    def test_team_foul_penalty(self) -> None:
        self.assertFalse(
            NBA_2025_26.in_team_foul_penalty(
                period=1,
                period_clock_ms=300_000,
                team_fouls_after_foul=4,
                last_two_minute_fouls_after_foul=0,
            )
        )
        self.assertTrue(
            NBA_2025_26.in_team_foul_penalty(
                period=1,
                period_clock_ms=300_000,
                team_fouls_after_foul=5,
                last_two_minute_fouls_after_foul=0,
            )
        )
        self.assertTrue(
            NBA_2025_26.in_team_foul_penalty(
                period=1,
                period_clock_ms=90_000,
                team_fouls_after_foul=2,
                last_two_minute_fouls_after_foul=2,
            )
        )


class EventSourcingTests(unittest.TestCase):
    def test_event_replay_reconstructs_state(self) -> None:
        state = GameState.initial(
            home_team="HOM",
            away_team="AWY",
            opening_possession="HOM",
            rules=NBA_2025_26,
        )
        emitter = EventEmitter(state, NBA_2025_26)
        emitter.emit(EventType.GAME_STARTED)
        emitter.emit(EventType.PERIOD_STARTED, period=1)
        emitter.emit(EventType.POSSESSION_STARTED, team="HOM")
        emitter.advance_clock(7.25)
        emitter.emit(
            EventType.SHOT_MADE,
            team="HOM",
            player_id=1,
            points=3,
        )
        emitter.emit(EventType.POSSESSION_CHANGED, team="AWY")
        emitter.emit(
            EventType.FOUL,
            team="HOM",
            player_id=1,
        )

        replay = GameState.initial(
            home_team="HOM",
            away_team="AWY",
            opening_possession="HOM",
            rules=NBA_2025_26,
        )
        for event in emitter.log:
            replay.apply(event, NBA_2025_26)

        self.assertEqual(replay.score, state.score)
        self.assertEqual(replay.period_clock_ms, state.period_clock_ms)
        self.assertEqual(replay.shot_clock_ms, state.shot_clock_ms)
        self.assertEqual(replay.possession_team, state.possession_team)
        self.assertEqual(replay.team_fouls, state.team_fouls)
        self.assertEqual(replay.player_fouls, state.player_fouls)
        restored = pickle.loads(pickle.dumps(emitter.log[3]))
        self.assertEqual(restored.as_dict(), emitter.log[3].as_dict())


class RandomnessTests(unittest.TestCase):
    def test_namespaced_streams_are_deterministic_and_independent(self) -> None:
        factory = RandomStreamFactory(1729)
        first = factory.generator("possessions").random(8)
        _ = factory.generator("new-feature").random(100)
        second = factory.generator("possessions").random(8)
        self.assertEqual(first.tolist(), second.tolist())
        self.assertNotEqual(
            factory.seed_for("possessions"),
            factory.seed_for("rotations"),
        )


if __name__ == "__main__":
    unittest.main()
