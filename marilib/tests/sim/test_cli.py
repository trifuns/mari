import pytest
from click.testing import CliRunner
from rich.console import Console

from marilib.marilib_edge import MarilibEdge
from marilib.sim import Network, SimulatedGatewayAdapter
from marilib.sim.cli import main
from marilib.sim.events import Event, check_events, parse_events
from marilib.sim.runner import Session
from marilib.tui_edge import MarilibTUIEdge

EVENTS = """
[[event]]
at = 10.0
action = "remove"
node = 3

[[event]]
at = 15.0
action = "add"
node = 3

[[event]]
at = 20.0
action = "move"
node = 5
distance = 12.0
"""


def run_cli(*args, events: str | None = None, tmp_path=None):
    if events is not None:
        path = tmp_path / "events.toml"
        path.write_text(events)
        args = (*args, "--events", str(path))
    return CliRunner().invoke(main, ["run", *args])


def test_fast_run_reports_the_scripted_leave_rejoin_and_move(tmp_path):
    result = run_cli(
        "--nodes", "20", "--duration", "30", "--pacing", "fast", "--summary", events=EVENTS, tmp_path=tmp_path
    )
    assert result.exit_code == 0, result.output
    assert "20/20 nodes joined" in result.output
    assert "remove node 3: gateway saw it leave at" in result.output
    assert "add node 3: joined at" in result.output
    assert "move node 5 to 12.0 m: uplink PDR" in result.output
    node_3 = next(line.split() for line in result.output.splitlines() if line.split()[:1] == ["3"])
    assert node_3[2:4] == ["2", "1"]  # joins, left


def test_same_seed_and_events_give_the_same_summary(tmp_path):
    args = ("--nodes", "12", "--duration", "20", "--pacing", "fast", "--summary", "--seed", "7")
    first = run_cli(*args, events=EVENTS, tmp_path=tmp_path)
    second = run_cli(*args, events=EVENTS, tmp_path=tmp_path)
    summary = lambda out: out.split("\n", 1)[1]  # drop the wall-clock line
    assert summary(first.output) == summary(second.output)


def test_a_move_out_of_range_lowers_that_nodes_pdr():
    drops = []
    for seed in range(4):
        net = Network.for_nodes(20, seed=seed)
        session = Session(net, events=[Event(20.0, "move", 5, (12.0, 0.0))])
        session.run(60)
        before, rec = session.fired[0], session.recorder
        after = (rec.delivered[0x1005] - before.delivered) / (rec.attempts[0x1005] - before.attempts)
        drops.append(before.delivered / before.attempts - after)
    assert sum(drops) / len(drops) > 0.02


def test_fast_runs_measure_rtt_from_gateway_stamps():
    net = Network.for_nodes(5, seed=2)
    session = Session(net, probe_interval_s=0.5)
    session.run(10)
    assert all(session.recorder.rtt_slots[address] for address in net.nodes)
    assert all(0 < s < 2 * net.schedule.n_cells for v in session.recorder.rtt_slots.values() for s in v)


@pytest.mark.parametrize(
    "args, error",
    [
        (("--pacing", "fast"), "--pacing fast needs --duration"),
        (("--schedule", "nope", "--duration", "1", "--pacing", "fast"), "no mari schedule 'nope'"),
    ],
)
def test_bad_arguments_are_usage_errors(args, error):
    result = run_cli(*args)
    assert result.exit_code == 2
    assert error in result.output


def test_events_on_a_node_that_is_off_are_rejected(tmp_path):
    result = run_cli("--nodes", "2", "--duration", "1", "--pacing", "fast", events=EVENTS, tmp_path=tmp_path)
    assert result.exit_code == 2
    assert "node 3 is not on" in result.output


@pytest.mark.parametrize(
    "entry, error",
    [
        ({"at": 1, "action": "teleport", "node": 1}, "action must be one of"),
        ({"at": 1, "action": "move", "node": 1}, "'move' needs"),
        ({"at": 1, "action": "remove", "node": 1, "distance": 3}, "takes no position"),
        ({"at": 1, "action": "add"}, "missing 'node'"),
        ({"at": 1, "action": "add", "node": 1, "where": 2}, "unknown key(s) where"),
    ],
)
def test_malformed_events_are_rejected(entry, error):
    with pytest.raises(ValueError, match=error.replace("(", r"\(").replace(")", r"\)")):
        parse_events({"event": [entry]})


def test_events_are_sorted_and_checked_in_time_order():
    events = parse_events(
        {
            "event": [
                {"at": 5, "action": "add", "node": 2},
                {"at": 1, "action": "remove", "node": 2},
            ]
        }
    )
    assert [e.action for e in events] == ["remove", "add"]
    check_events(events, n_nodes=2)
    with pytest.raises(ValueError, match="already on"):
        check_events(events[1:], n_nodes=2)


def test_mari_edge_tui_renders_the_simulated_gateway():
    net = Network.for_nodes(4, seed=1)
    edge = MarilibEdge(lambda *_: None, serial_interface=SimulatedGatewayAdapter(net, realtime=False))
    try:
        net.run(net.slots_for(2))
        edge.update()
        tui, console = MarilibTUIEdge(), Console(width=200, record=True)
        console.print(tui.create_header_panel(edge), tui.create_nodes_panel(edge))
        text = console.export_text()
        assert "simulator:tiny" in text
        assert "0x0000000000001004" in text
    finally:
        edge.close()


def test_verify_is_a_subcommand():
    result = CliRunner().invoke(main, ["verify", "--help"])
    assert result.exit_code == 0
    assert "smallest schedule" in result.output
