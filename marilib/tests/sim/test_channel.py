import random
import statistics

import pytest

from marilib.sim.channel import DEFAULT_NODE_SPREAD_PTS, DistanceChannel


def fleet(n: int, seed: int = 0) -> DistanceChannel:
    channel = DistanceChannel()
    rng = random.Random(seed)
    for address in range(n):
        channel.add_node(address, rng)
    return channel


@pytest.mark.parametrize("distance, expected", [(0.5, 0.986), (2.0, 0.986), (6.0, 0.9645), (10.0, 0.943), (30.0, 0.943)])
def test_anchor_interpolation_is_clamped_at_the_ends(distance, expected):
    assert DistanceChannel().base_pdr(distance) == pytest.approx(expected)


@pytest.mark.parametrize("distance, anchor", [(2.0, 0.986), (10.0, 0.943)])
def test_fleet_mean_stays_near_the_anchor(distance, anchor):
    channel = fleet(5000)
    mean = statistics.mean(channel.pdr(a, distance) for a in range(5000))
    assert mean == pytest.approx(anchor, abs=0.003)


def test_no_node_sits_more_than_the_spread_above_the_anchor():
    channel = fleet(2000)
    best = max(channel.pdr(a, 10.0) for a in range(2000))
    assert best <= 0.943 + DEFAULT_NODE_SPREAD_PTS / 100 + 1e-12


def test_the_spread_is_the_same_at_both_anchors():
    channel = fleet(50, seed=3)
    spans = [max(p) - min(p) for p in ([channel.pdr(a, d) for a in range(50)] for d in (2.0, 10.0))]
    assert spans[0] == pytest.approx(spans[1], abs=0.03)
