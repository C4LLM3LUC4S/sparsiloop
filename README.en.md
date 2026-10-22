# SparsiLoop · Event-triggered control lab

**Compare control error with the messages it actually costs.**

SparsiLoop is a local lab for students and control researchers to compare event-triggered and periodic feedback under packet budgets, delay and loss. Inspect every message, keep failed cases visible and export reproducible trajectories and metrics.

[中文](README.md) · [Protocol](docs/protocol.md) · [Post-hoc traffic study](docs/traffic-study.md) · [Grid check](docs/grid-check.md)

Integrating an existing controller? The [pinned simple-pid recipe](docs/simple-pid.md) uses a simulation clock, received-observation gaps and fresh PID state, then exports provenance and every P/I/D update. Its optional dependency is separate from the standard-library core.

**Version 0.0.1: development prototype, not a public release.** It currently has two normalized teaching plants, three sensor-to-controller schedules and a fixed linear controller. It does not establish stability, hardware safety, paper reproduction or independent adoption.

## Run locally

Python 3.10 or later. The simulator and local web server use only the Python standard library; no account, model, API key or GPU is required. From this source folder:

```sh
python -m event_control_lab serve --port 8788
```

Open the displayed loopback URL. Set a maximum packet budget, delay and loss probability, then run the comparison. A common maximum budget is not equal actual traffic. The lower section scans all declared thresholds and seeds and builds a separate periodic reference at the event run's actual attempted packet count.

Check sensitivity to sampling at fixed physical schedules:

```sh
python -m event_control_lab grid-check --spec examples/grid-check.json --out runs/grid-check
```

This deterministic check reports grid-dependent event changes separately from position RMSE quadrature error. It exports all trajectories and retains failed runs; it does not certify convergence. See the [grid-check guide](docs/grid-check.md) for input constraints and output fields.

```sh
python -m event_control_lab compare --config examples/default.json --out runs/first
python -m event_control_lab study --spec examples/traffic-study.json --out runs/traffic-check
python -m unittest discover -s tests -v
```

Output folders must be new. Full JSON includes configurations, source fingerprints, external random inputs, packet accounting and raw trajectories. Study exports retain every declared pair and its eligibility reasons; failures do not receive a zero score. Post-hoc references use observed traffic after each event run, so they are descriptive diagnostics, not prospective tuning or independent performance evidence.

## Use your own controller

```python
from event_control_lab import Config, compare

class MyController:
    def __call__(self, observation):
        return -2.0 * observation.values[0]

result = compare(Config(), controller_factory=lambda config: MyController())
```

Each schedule gets a new controller instance. Only delivered measurements and their sample/arrival times are supplied; inputs are held between arrivals. Save custom source, weights and random state separately. A local Python callable is not a sandbox, and the web UI does not run uploaded code.

SparsiLoop is the project name; `event_control_lab` remains the Python module name. See [project status](PROJECT_STATUS.md) for actual checks and remaining work. MIT licensed.
