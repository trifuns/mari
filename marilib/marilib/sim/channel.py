"""Link models: the probability that a single transmission between a node and the gateway arrives.

A link model sees a node and a distance, never the node count or the schedule:
PDR on hardware tracks distance and the individual bot, and a model that let N
leak in would reproduce the selection-bias artifact the reference campaign had
to correct for.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Protocol

# Single-attempt PDR by distance, from the mari single-gateway dongle campaign
# (the mari paper's latency/PDR-vs-swarm-size benchmark).
DEFAULT_PDR_ANCHORS = ((2.0, 0.986), (10.0, 0.943))

# Scale, in PDR points, of each node's fixed offset. The campaign measured a
# best-to-worst range of 11.8 points at 2 m and 11.7 at 10 m, the same at both
# distances; this scale gives 10 to 11.7 points across 50 nodes.
DEFAULT_NODE_SPREAD_PTS = 2.6


class ChannelModel(Protocol):
    def add_node(self, address: int, rng: random.Random) -> None:
        """Draw whatever per-node state the model keeps; called once per node, in join order."""

    def pdr(self, address: int, distance_m: float) -> float:
        """Probability that one frame between this node and the gateway is received."""

    def rssi_dbm(self, address: int, distance_m: float) -> int:
        """RSSI reported for a received frame, for the probe's rssi fields."""


@dataclass
class PerfectChannel:
    """Every frame arrives. For tests that need the MAC alone."""

    def add_node(self, address: int, rng: random.Random) -> None:
        pass

    def pdr(self, address: int, distance_m: float) -> float:
        return 1.0

    def rssi_dbm(self, address: int, distance_m: float) -> int:
        return -50


@dataclass
class DistanceChannel:
    """PDR interpolated over distance anchors, plus a fixed offset per node.

    The offset is `spread * (1 - E)` points with E ~ Exp(1): mean zero, at most
    `spread` above the anchor and a long tail below it, the shape of a fleet
    where most bots sit near the anchor and a few are persistently poor. PDR is
    clipped to [0, 1], which pulls the 2 m fleet mean about 0.2 points under
    its anchor.
    """

    anchors: tuple[tuple[float, float], ...] = DEFAULT_PDR_ANCHORS
    node_spread_pts: float = DEFAULT_NODE_SPREAD_PTS
    _offset: dict[int, float] = field(default_factory=dict, repr=False)

    def add_node(self, address: int, rng: random.Random) -> None:
        self._offset[address] = self.node_spread_pts / 100 * (1 - rng.expovariate(1.0))

    def base_pdr(self, distance_m: float) -> float:
        points = sorted(self.anchors)
        if distance_m <= points[0][0]:
            return points[0][1]
        for (d0, p0), (d1, p1) in zip(points, points[1:]):
            if distance_m <= d1:
                return p0 + (distance_m - d0) / (d1 - d0) * (p1 - p0)
        return points[-1][1]

    def pdr(self, address: int, distance_m: float) -> float:
        return min(1.0, max(0.0, self.base_pdr(distance_m) + self._offset.get(address, 0.0)))

    def rssi_dbm(self, address: int, distance_m: float) -> int:
        # free-space slope from -40 dBm at 1 m; only feeds the probe's rssi fields
        return round(-40 - 20 * math.log10(max(distance_m, 0.1)))
