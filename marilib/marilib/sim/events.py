"""Scripted changes to a running network, keyed by simulated time.

    [[event]]
    at = 10.0          # seconds since the run started
    action = "remove"  # "add", "remove" or "move"
    node = 3           # node 3 is address 0x1003, the third node Network.for_nodes made

    [[event]]
    at = 20.0
    action = "move"
    node = 5
    distance = 12.0    # meters from the gateway, or position = [x, y]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from marilib.sim.network import DEFAULT_NODE_ADDRESS_BASE

ACTIONS = ("add", "remove", "move")


@dataclass(frozen=True)
class Event:
    at_s: float
    action: str
    node: int
    position: tuple[float, float] | None = None

    @property
    def address(self) -> int:
        return DEFAULT_NODE_ADDRESS_BASE + self.node

    def describe(self) -> str:
        text = f"{self.action} node {self.node}"
        if self.position is not None:
            text += f" to {math.hypot(*self.position):.1f} m"
        return text


def parse_events(data: dict) -> list[Event]:
    """Events from a parsed TOML document, sorted by time. Raises ValueError on a bad entry."""
    events = []
    for i, entry in enumerate(data.get("event", [])):
        where = f"event {i + 1}"
        unknown = set(entry) - {"at", "action", "node", "distance", "position"}
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        try:
            at_s, action, node = float(entry["at"]), entry["action"], int(entry["node"])
        except KeyError as missing:
            raise ValueError(f"{where}: missing {missing}") from None
        if action not in ACTIONS:
            raise ValueError(f"{where}: action must be one of {', '.join(ACTIONS)}, got {action!r}")
        if at_s < 0 or node < 1:
            raise ValueError(f"{where}: 'at' must be >= 0 and 'node' >= 1")
        if "distance" in entry and "position" in entry:
            raise ValueError(f"{where}: give 'distance' or 'position', not both")
        position = None
        if "distance" in entry:
            position = (float(entry["distance"]), 0.0)
        elif "position" in entry:
            x, y = entry["position"]
            position = (float(x), float(y))
        if action == "move" and position is None:
            raise ValueError(f"{where}: 'move' needs 'distance' or 'position'")
        if action == "remove" and position is not None:
            raise ValueError(f"{where}: 'remove' takes no position")
        events.append(Event(at_s, action, node, position))
    return sorted(events, key=lambda e: e.at_s)


def load_events(path: str | Path) -> list[Event]:
    import tomllib

    with open(path, "rb") as f:
        return parse_events(tomllib.load(f))


def check_events(events: list[Event], n_nodes: int) -> None:
    """Raise ValueError if an event acts on a node that is not powered at that point."""
    present = set(range(1, n_nodes + 1))
    for event in events:
        if event.action == "add":
            if event.node in present:
                raise ValueError(f"at {event.at_s} s: node {event.node} is already on")
            present.add(event.node)
        elif event.node not in present:
            raise ValueError(f"at {event.at_s} s: node {event.node} is not on")
        elif event.action == "remove":
            present.discard(event.node)
