"""Offline wheel checks and tests from a separately extracted source distribution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv


PROBE = r'''
from dataclasses import asdict
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from importlib import metadata, resources
import json
from pathlib import Path
from threading import Thread
import hashlib
import event_control_lab
from event_control_lab import Config, GridSpec, PlantAdapter, StudySpec, compare, grid_check, study
from event_control_lab.server import Handler
from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from dataclasses import replace
import base64
import io
import zipfile
from event_control_lab.policy import checkpoint, evaluate_policy
from event_control_lab.planned_study import PlannedSpec, select_schedule, test_schedule

config = Config(duration=0.8, budget=4, heartbeat=0.2, measurement_noise=0,
                process_noise=0, loss_probability=0)
spec = StudySpec(config=config, thresholds=(0.06, 0.12), seeds=(20261022,))
single, scanned = compare(config), study(spec)
learning_spec = ControllerLabSpec()
learning_spec = replace(learning_spec, config=replace(learning_spec.config, duration=0.2, budget=10),
                        ilc_trials=2, training_seeds=(101, 102), evaluation_seeds=(2001,))
learning = controller_lab(learning_spec)
planned_spec = PlannedSpec(config=Config(duration=0.8, dt=0.1, budget=8, heartbeat=0.8,
    delay_steps=0, measurement_noise=0, process_noise=0, loss_probability=0),
    absolute_thresholds=(2,), relative_thresholds=(2,), selection_seeds=(91, 92),
    test_seeds=(93, 94), rmse_limit=100)
planned_selection = select_schedule(planned_spec)
planned_test = test_schedule(planned_selection)

adapter = PlantAdapter("installed-package constant model", "scalar",
                       lambda config: lambda state, held_input, dt: (0.5,),
                       parameters={"constant": 0.5}, source="original distribution-check fixture")
custom_compare = compare(config, plant=adapter)
custom_study = study(spec, plant=adapter)
custom_learning = controller_lab(learning_spec, plant=adapter)
assert all(run["trajectory"][1]["state"] == [0.5] for run in custom_compare["runs"])

class QuietHandler(Handler):
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
worker = Thread(target=server.serve_forever, daemon=True)
worker.start()
api_checks = {}
try:
    for route, payload, expected in (("/api/compare", asdict(config), single),
                                     ("/api/study", asdict(spec), scanned)):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request("POST", route, body=json.dumps(payload))
            response = connection.getresponse()
            assert response.status == 200, (route, response.status)
            api_checks[route] = json.loads(response.read()) == json.loads(json.dumps(expected))
            assert api_checks[route], route
        finally:
            connection.close()
    for route, payload, expected_file, expected in (
        ("/api/controllers", {"method": "ilc", "spec": asdict(learning_spec)},
         "controllers.json", controller_lab(learning_spec, "ilc")),
        ("/api/evaluate-policy", {"checkpoint": checkpoint(learning), "seeds": [3001]},
         "evaluation.json", evaluate_policy(checkpoint(learning), [3001])),
    ):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request("POST", route, body=json.dumps(payload))
            response = connection.getresponse()
            assert response.status == 200, (route, response.status)
            result = json.loads(response.read())
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(result["archive_base64"]))) as archive:
                assert archive.testzip() is None
                api_checks[route] = json.loads(archive.read(expected_file)) == json.loads(json.dumps(expected))
                assert api_checks[route], route
        finally:
            connection.close()
finally:
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)

try:
    data = metadata.metadata("sparsiloop")
except metadata.PackageNotFoundError:
    data = None
print(json.dumps({
    "origin": str(Path(event_control_lab.__file__).resolve()),
    "distribution": data["Name"] if data else None,
    "version": event_control_lab.__version__,
    "runtime_dependencies": data.get_all("Requires-Dist", []) if data else None,
    "static_sha256": {name: hashlib.sha256(resources.files("event_control_lab.web").joinpath(name).read_bytes()).hexdigest()
                      for name in ("index.html", "style.css", "app.js", "study.js", "controllers.js")},
    "compare": single, "study": scanned, "grid_check": grid_check(GridSpec(config)),
    "controller_lab": learning,
    "planned_selection": planned_selection, "planned_test": planned_test,
    "custom_model": {"compare": custom_compare, "study": custom_study, "controller_lab": custom_learning},
    "installed_http_api_matches_direct_calls": api_checks,
}))
'''


def run(command, cwd, logs, name):
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    for suffix, content in (("stdout", process.stdout), ("stderr", process.stderr)):
        (logs / f"{name}.{suffix}.log").write_text(content, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"{name} failed ({process.returncode}): {process.stderr[-3000:]}")
    return process


def extract_source(archive, destination):
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > 1000 or sum(item.size for item in members) > 100_000_000:
            raise ValueError("unexpectedly large source distribution")
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError("source archive contains an unsafe path or link")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as content, target.open("xb") as output:
                    shutil.copyfileobj(content, output)
    roots = list(destination.iterdir())
    if len(roots) != 1 or not (roots[0] / "pyproject.toml").is_file():
        raise ValueError("source distribution must contain one project root")
    return roots[0]


def within_directory(path, directory):
    # Windows may report RUNNER~1 for one side and runneradmin for the other.
    return Path(path).resolve(strict=True).is_relative_to(Path(directory).resolve(strict=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    logs = arguments.out.resolve()
    logs.mkdir(parents=True, exist_ok=False)
    wheel, archive = arguments.wheel.resolve(), arguments.sdist.resolve()
    with tempfile.TemporaryDirectory(prefix="SparsiLoop package check ") as temporary:
        base = Path(temporary)
        environment = base / "isolated environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
            base, logs, "offline-install")
        installed = json.loads(run([str(python), "-I", "-c", PROBE], base, logs, "installed-probe").stdout)
        source = json.loads(run([sys.executable, "-c", PROBE], project, logs, "source-probe").stdout)
        if not within_directory(installed["origin"], environment):
            raise ValueError("installed import escaped the fresh environment")
        if not within_directory(source["origin"], project / "event_control_lab"):
            raise ValueError("source comparison imported a different package")
        if installed["runtime_dependencies"]:
            raise ValueError("unexpected runtime dependency")
        if installed["distribution"] != "sparsiloop" or installed["runtime_dependencies"] is None:
            raise ValueError("installed distribution metadata is missing or misnamed")
        for key in ("version", "static_sha256", "compare", "study", "grid_check", "controller_lab", "custom_model", "planned_selection", "planned_test"):
            if installed[key] != source[key]:
                raise ValueError(f"installed/source mismatch: {key}")
        for command in ("sparsiloop", "event-control-lab"):
            executable = scripts / (command + ".exe" if os.name == "nt" else command)
            version = run([str(executable), "--version"], base, logs, command + "-entrypoint")
            if version.stdout.strip() != "SparsiLoop " + installed["version"]:
                raise ValueError("command entry point version mismatch")
        cli_output = base / "installed grid output"
        run([str(python), "-I", "-m", "event_control_lab", "grid-check", "--spec",
             str(project / "examples/grid-check.json"), "--out", str(cli_output)], base, logs, "installed-grid-cli")
        if len(json.loads((cli_output / "grid.json").read_text(encoding="utf-8"))["summaries"]) != 9:
            raise ValueError("installed grid CLI did not export all requested runs")
        controller_output = base / "installed controller output"
        run([str(python), "-I", "-m", "event_control_lab", "controller-lab", "--method", "ilc",
             "--out", str(controller_output)], base, logs, "installed-controller-cli")
        if not all((controller_output / name).is_file() for name in
                   ("controllers.json", "summary.csv", "trajectories.csv", "report.html")):
            raise ValueError("installed controller CLI omitted required outputs")
        planned_spec = base / "planned spec.json"
        planned_spec.write_text(json.dumps(installed["planned_selection"]["spec"]), encoding="utf-8")
        chosen, tested = base / "planned choice", base / "planned test"
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "select", "--spec",
             str(planned_spec), "--out", str(chosen)], base, logs, "installed-planned-select")
        original = (chosen / "selection.json").read_bytes()
        if json.loads(original) != installed["planned_selection"]:
            raise ValueError("installed planned selection CLI differs from API")
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "test",
             str(chosen / "selection.json"), "--out", str(tested)], base, logs, "installed-planned-test")
        if json.loads((tested / "test.json").read_bytes()) != installed["planned_test"]:
            raise ValueError("installed planned test CLI differs from API")
        if (chosen / "selection.json").read_bytes() != original:
            raise ValueError("planned test changed its input record")
        extracted = extract_source(archive, base / "fresh source")
        for path in ("README.md", "README.en.md", "BRANDING.md", "START_HERE.md", "quickstart.py", "docs/grid-check.md",
                     "examples/grid-check.json", "examples/own_model_case.py", "docs/own-model.md", "scripts/check_distribution.py", "docs/planned-study.md",
                     "examples/planned-study.json", "event_control_lab/planned_study.py",
                     "event_control_lab/planned_report.py", "event_control_lab/planned_cli.py"):
            if (extracted / path).read_bytes() != (project / path).read_bytes():
                raise ValueError(f"source distribution omitted or changed {path}")
        extracted_origin = run([str(python), "-c", "import event_control_lab; print(event_control_lab.__file__)"],
                               extracted, logs, "extracted-origin").stdout.strip()
        if not within_directory(extracted_origin, extracted):
            raise ValueError("source-distribution test origin is not the extracted source")
        run([str(python), "-I", str(extracted / "quickstart.py"), "--mode", "controllers",
             "--method", "ilc", "--no-open", "--out", str(base / "extracted quickstart output")],
            base, logs, "extracted-quickstart")
        model_output = base / "extracted own model output"
        run([str(python), "-m", "examples.own_model_case", "--out", str(model_output)],
            extracted, logs, "extracted-own-model-case")
        model_result = json.loads((model_output / "network/result.json").read_text(encoding="utf-8"))
        model_source = extracted / "examples/own_model_case.py"
        if model_result["plant"]["source_sha256"] != hashlib.sha256(model_source.read_bytes()).hexdigest():
            raise ValueError("custom-model recipe did not retain its own source fingerprint")
        if not (model_output / "controllers/report.html").is_file():
            raise ValueError("custom-model recipe did not produce its learning report")
        tests = run([str(python), "-m", "unittest", "discover", "-s", "tests", "-v"],
                    extracted, logs, "fresh-source-tests")
        count = re.search(r"Ran (\d+) tests", tests.stderr)
        if not count or not re.search(r"(?m)^OK(?: \(skipped=\d+\))?\s*$", tests.stderr):
            raise ValueError("source-distribution test result was not recognized")
        summary = {
            "status": "passed", "distribution": installed["distribution"], "version": installed["version"],
            "python_version": sys.version.split()[0], "platform": sys.platform,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "sdist_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "no_runtime_dependencies": True, "fresh_offline_install": True,
            "isolated_import_verified": True, "compare_study_grid_match_source": True,
            "static_resources_match_source": True,
            "both_command_entry_points": True, "installed_grid_cli": True,
            "installed_controller_cli_and_result_parity": True,
            "installed_planned_selection_and_test_match_source": True,
            "installed_custom_model_compare_study_learning_match_source": True,
            "extracted_own_model_recipe_and_provenance": True,
            "installed_http_api": installed["installed_http_api_matches_direct_calls"],
            "fresh_source_tests_passed": int(count.group(1)),
            "publicly_released": False,
            "github_actions_invocation": os.environ.get("GITHUB_ACTIONS") == "true",
            "verification_scope": "This invocation only; other platforms and Python versions are not inferred",
        }
    (logs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
