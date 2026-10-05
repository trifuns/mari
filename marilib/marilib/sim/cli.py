"""mari-sim: run a simulated mari network, live under the mari-edge TUI or as fast as it goes."""

from __future__ import annotations

import threading
import time

import click

from marilib.sim.events import check_events, load_events
from marilib.sim.network import Network
from marilib.sim.runner import Session
from marilib.sim.verify import main as verify


@click.group()
def main():
    """Simulate a mari gateway and its nodes, slot by slot."""


@main.command()
@click.option("--nodes", "-n", "n_nodes", default=10, show_default=True, help="Nodes powered at start.")
@click.option(
    "--schedule",
    "-s",
    default="auto",
    show_default=True,
    help="Schedule name, or auto for the smallest one that fits --nodes.",
)
@click.option("--seed", default=0, show_default=True, help="Same seed and events, same run.")
@click.option(
    "--distance", default=2.0, show_default=True, help="Meters from the gateway, for every node."
)
@click.option(
    "--duration", type=float, default=None, help="Simulated seconds. Default: until Ctrl-C."
)
@click.option(
    "--pacing",
    type=click.Choice(["realtime", "fast"]),
    default="realtime",
    show_default=True,
    help="realtime shows the mari-edge TUI; fast runs headless as fast as it can.",
)
@click.option(
    "--metrics-probe-interval",
    "-i",
    default=1.0,
    show_default=True,
    help="Seconds between probes to the same node; 0 disables RTT measurement.",
)
@click.option(
    "--events",
    "events_path",
    type=click.Path(exists=True, dir_okay=False),
    help="TOML file of add / remove / move events (see marilib.sim.events).",
)
@click.option(
    "--trace", "trace_file", type=click.File("w"), help="Write the JSON-lines event trace here."
)
@click.option("--summary", is_flag=True, help="Print per-node PDR, RTT and event outcomes at the end.")
def run(
    n_nodes, schedule, seed, distance, duration, pacing, metrics_probe_interval, events_path,
    trace_file, summary,
):  # fmt: skip
    """Run a network of --nodes stock nodes around one gateway."""
    if pacing == "fast" and duration is None:
        raise click.UsageError("--pacing fast needs --duration")
    if metrics_probe_interval < 0:
        raise click.BadParameter("must be >= 0", param_hint="--metrics-probe-interval")
    try:
        events = load_events(events_path) if events_path else []
        check_events(events, n_nodes)
    except ValueError as error:
        raise click.BadParameter(str(error), param_hint="--events") from None
    try:
        net = Network.for_nodes(
            n_nodes, schedule=None if schedule == "auto" else schedule, seed=seed, distance_m=distance
        )
    except KeyError as error:
        raise click.BadParameter(error.args[0], param_hint="--schedule") from None

    fast = pacing == "fast"
    session = Session(
        net,
        events=events,
        probe_interval_s=metrics_probe_interval if fast else 0.0,
        default_distance_m=distance,
        trace_stream=trace_file,
    )
    started = time.monotonic()
    if fast:
        session.run(duration)
    else:
        _run_with_tui(session, duration, metrics_probe_interval)
    wall = time.monotonic() - started
    session.recorder.close()

    click.echo(
        f"{session.seconds(net.asn):.1f} s simulated in {wall:.1f} s ({pacing}), "
        f"{net.joined_count}/{len(net.nodes)} nodes joined"
    )
    if net.realtime_lag_slots:
        click.echo(f"{net.realtime_lag_slots} slots started late against the wall clock")
    if summary:
        click.echo("\n" + session.summary())


def _run_with_tui(session: Session, duration: float | None, probe_interval_s: float) -> None:
    """The stock MarilibEdge and its TUI on the simulated UART; the network runs on its own thread."""
    from marilib.marilib_edge import MarilibEdge
    from marilib.sim.adapter import SimulatedGatewayAdapter
    from marilib.tui_edge import MarilibTUIEdge

    adapter = SimulatedGatewayAdapter(session.net, realtime=False)
    edge = MarilibEdge(
        lambda *_: None,
        serial_interface=adapter,
        tui=MarilibTUIEdge(),
        main_file=__file__,
        metrics_probe_period=probe_interval_s,
    )
    session.tap_uart()
    stop = threading.Event()
    thread = threading.Thread(
        target=session.run,
        args=(duration,),
        kwargs={"realtime": True, "stop": stop},
        name="mari-sim",
        daemon=True,
    )
    thread.start()
    try:
        while thread.is_alive():
            edge.update()
            edge.render_tui()
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join()
        edge.close_tui()
        edge.close()


main.add_command(verify, name="verify")


if __name__ == "__main__":
    main()
