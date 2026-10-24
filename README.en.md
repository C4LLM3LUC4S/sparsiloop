# SparsiLoop · Event-triggered control lab

**What happens to control error when you send fewer sensor messages?**

Try it on your computer: set a message limit, delay and loss probability, then compare regular sending with sending when measurements change. See where errors grow, check which messages arrived and save the results for analysis. The teaching models give you a starting point; a local Python adapter lets you bring your own model.

[中文](README.md) · [Start here](START_HERE.md) · [Protocol](docs/protocol.md)

**Version `0.1.0a2`: alpha update for selection evidence and bounded local requests.** It provides two normalized teaching plants, three sensor-to-controller schedules and separate learning recipes. Controllers see only received observations. The core and local web server use Python 3.10+ and the standard library; no account, API key or GPU is needed. The prototype does not certify stability or hardware safety, reproduce a paper, or establish independent adoption.


**[下载完整离线包 / Complete offline bundle](https://github.com/C4LLM3LUC4S/sparsiloop/releases/download/v0.1.0a2/SparsiLoop-0.1.0a2.zip)** · [发行说明与校验 / Release and checksums](https://github.com/C4LLM3LUC4S/sparsiloop/releases/tag/v0.1.0a2) · [旧文件与源码恢复 / Saved-file recovery](docs/source-recovery.md)

## Start with your task

Start with one decision and a retained recheck. [Practical value and local workload](docs/reliability.md) explains the acceptance path, shared computation admission and connection limits; this is a local lab rather than a shared cloud service.

| What you want to do | Where to start |
| --- | --- |
| Explore the effect of fewer messages | Run `python quickstart.py` and compare error with actual attempted messages |
| Choose a schedule before inspecting test outcomes | [Planned selection](docs/planned-study.md), in the web lab or CLI; keep all candidates and failures, without test-based reselection |
| Reuse a trained scalar Q policy | [Frozen-policy workflow](docs/planned-policy.md), using a complete saved file or the preceding web result; no retraining |
| Continue across standalone evaluations and later plans | [Chronological history](docs/policy-history.md) in the web interface or local CLI/Python; retain the supplied origin and subsequent phases |
| Bring your own plant | [Local-model workflow](docs/planned-models.md), retaining explicit parameters, units and source; no browser upload of Python code |
| Repeat on another machine or redraw old results | [Environment and redraw guide](docs/planned-study.md#换一台电脑时先看环境记录); missing old facts stay unknown |

Integrating an existing PID controller? The [pinned simple-pid recipe](docs/simple-pid.md) uses a simulation clock, received-observation gaps and fresh PID state, then exports provenance and each P/I/D update. Its optional dependency is separate from the standard-library core. [Post-hoc traffic study](docs/traffic-study.md) and [grid check](docs/grid-check.md) describe the other comparison protocols.

## Run locally

Shortest source-preview path: extract the repository, then `python quickstart.py` for the web lab or `python quickstart.py --mode controllers` for static learning reports. It needs no installation or environment activation. See [Start here](START_HERE.md).

Download and extract this repository's source ZIP, or clone `https://github.com/C4LLM3LUC4S/sparsiloop.git`, then enter the project folder.

Python 3.10 or later. The simulator and local web server use only the Python standard library; no account, model, API key or GPU is required. From this source folder:

```sh
python -m event_control_lab serve --port 8788
```

Open the displayed loopback URL. Set a maximum packet budget, delay and loss probability, then run the comparison. A common maximum budget is not equal actual traffic. The lower section scans all declared thresholds and seeds and builds a separate periodic reference at the event run's actual attempted packet count.

Run the [MFAC, ILC and reinforcement-learning recipes](docs/classic-controllers.md):

You can also configure them in the [web lab](docs/web-recipes.md), download a complete offline report ZIP, or load a saved checkpoint for testing on new seeds. Training and test results stay separate. The CLI below supports a wider workload and parameter range.

```sh
python -m event_control_lab controller-lab --out runs/controllers
```

Open `report.html` in the new output folder. The scalar teaching recipes retain online estimates, all repeated trials, training/evaluation seed separation, frozen policy checkpoints, failed cases and untrained/fixed-feedback references. MFAC and ILC currently require full-rate regular observations; they are not advertised as general event-triggered variants. Use `--method mfac`, `ilc` or `rl` for one recipe. The installed wheel supports the same command without example files or extra dependencies.

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

Have your own dynamics? The [local plant adapter](docs/own-model.md) connects a declared single-input scalar or position–velocity model to network comparisons, post-hoc references and MFAC/ILC/RL recipes. Run `python -m examples.own_model_case --out runs/own-model` for a complete report. Retain model source, parameters, units and an independent known-input check. See [product tasks and acceptance](docs/product-scope.md).

```python
from event_control_lab import Config, compare

class MyController:
    def __call__(self, observation):
        return -2.0 * observation.values[0]

result = compare(Config(), controller_factory=lambda config: MyController())
```

Each schedule gets a new controller instance. Only delivered measurements and their sample/arrival times are supplied; inputs are held between arrivals. Save custom source, weights and random state separately. A local Python callable is not a sandbox, and the web UI does not run uploaded code.

SparsiLoop is the project name; `event_control_lab` remains the Python module name. See [supported tasks and limits](docs/product-scope.md) for scope, and [GitHub Actions](https://github.com/C4LLM3LUC4S/sparsiloop/actions) for checks on a specific commit. MIT licensed.
