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
from event_control_lab.web_planned import default_specification as planned_default
from event_control_lab.planned_context import as_bundle, select_with_context, test_with_context, validate_context
from event_control_lab.policy_journal import evaluate_saved, select_plan, test_plan, load_workflow

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
web_planned_spec = PlannedSpec.from_dict(planned_default())
web_planned_spec = replace(web_planned_spec, config=replace(web_planned_spec.config, duration=0.2,
    heartbeat=0.2, budget=10), selection_seeds=(801,), test_seeds=(802,))
web_selection = select_schedule(web_planned_spec)
contextual_choice = select_with_context(planned_spec)
contextual_test = test_with_context(contextual_choice)
assert contextual_choice["result"] == planned_selection
assert contextual_test["result"] == planned_test
assert contextual_test["context"]["selection"] == contextual_choice["context"]["selection"]
validate_context(contextual_test["context"], contextual_test["result"])

adapter = PlantAdapter("installed-package constant model", "scalar",
                       lambda config: lambda state, held_input, dt: (0.5,),
                       parameters={"constant": 0.5}, source="original distribution-check fixture")
custom_compare = compare(config, plant=adapter)
custom_study = study(spec, plant=adapter)
custom_learning = controller_lab(learning_spec, plant=adapter)
assert all(run["trajectory"][1]["state"] == [0.5] for run in custom_compare["runs"])
planned_adapter = replace(adapter, source="Retained inline fixture: lambda config: lambda state, held_input, dt: (0.5,)",
    source_sha256=hashlib.sha256(b"lambda config: lambda state, held_input, dt: (0.5,)").hexdigest())
model_choice = select_with_context(planned_spec, plant=planned_adapter)
model_test = test_with_context(model_choice, plant=planned_adapter)
assert model_test["context"]["selection"] == model_choice["context"]["selection"]
assert all(row["run"]["plant"] == planned_adapter.metadata() for row in model_test["result"]["test_runs"])
frozen_spec = replace(planned_spec, config=replace(learning_spec.config, budget=5, initial_position=0.75),
    previously_used_seeds=(7001,))
frozen_choice = select_with_context(frozen_spec, policy_checkpoint=checkpoint(learning))
frozen_test = test_with_context(frozen_choice)
assert frozen_test["context"]["selection"] == frozen_choice["context"]["selection"]
assert [row["phase"] for row in frozen_test["result"]["policy_after"]["planned_history"]] == ["selection", "test"]
assert frozen_test["result"]["policy_after"]["declared_development_seeds"] == [7001]
journal_origin = frozen_test["result"]["policy_after"]
journal_spec = replace(frozen_spec, selection_seeds=(13001,), test_seeds=(14001,), previously_used_seeds=(15001,))
journal_evaluation = evaluate_saved(journal_origin, [9001])
journal_choice = select_plan(journal_spec, journal_evaluation["history_after"])
journal_test = test_plan(journal_choice)
for saved_workflow in (journal_evaluation, journal_choice, journal_test):
    load_workflow(saved_workflow)
journal_history = {key:value for key,value in journal_test["history_after"].items()
                   if key not in ("events", "history_sha256")}
journal_history["events"] = [{key:value for key,value in event.items() if key != "runtime"}
                             for event in journal_test["history_after"]["events"]]

class QuietHandler(Handler):
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
worker = Thread(target=server.serve_forever, daemon=True)
worker.start()
api_checks = {}
frozen_web_checks = {}
web_saved_bundle = None
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
        ("/api/planned/select", {"spec": asdict(web_planned_spec)}, "selection.json", web_selection),
        ("/api/planned/test", {"selection": web_selection}, "test.json", test_schedule(web_selection)),
    ):
        if route == "/api/planned/test":
            assert web_saved_bundle is not None
            payload = {"selection": web_saved_bundle}
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
                if route.startswith("/api/planned/"):
                    saved = as_bundle(json.loads(archive.read("selection-bundle.json")))
                    manifest = json.loads(archive.read("environment.json"))
                    assert manifest["execution"] == result["context"]
                    assert manifest["report_rendering"] == result["report_runtime"]
                    validate_context(result["context"], result["record"])
                    if route.endswith("/select"):
                        web_saved_bundle = saved
                        assert saved["context"]["selection"]["state"] == "recorded"
                    else:
                        assert result["context"]["selection"] == web_saved_bundle["context"]["selection"]
                        assert as_bundle(json.loads(archive.read("test-bundle.json")))["result"] == result["record"]
        finally:
            connection.close()
    frozen_saved = None
    for phase, payload, expected in (
        ("select", {"spec": asdict(frozen_spec), "policy_checkpoint": checkpoint(learning)}, frozen_choice["result"]),
        ("test", None, frozen_test["result"]),
    ):
        if phase == "test":
            payload = {"selection": frozen_saved}
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request("POST", "/api/planned/" + phase, body=json.dumps(payload))
            response = connection.getresponse()
            assert response.status == 200, (phase, response.status)
            value = json.loads(response.read())
            assert value["record"] == json.loads(json.dumps(expected))
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(value["archive_base64"]))) as archive:
                assert archive.testzip() is None
                assert json.loads(archive.read("policy-history.json")) == value["record"]["policy_after"]
                if phase == "select":
                    frozen_saved = json.loads(archive.read("selection-bundle.json"))
            frozen_web_checks[phase] = True
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
                      for name in ("index.html", "style.css", "app.js", "study.js", "controllers.js", "planned.js")},
    "compare": single, "study": scanned, "grid_check": grid_check(GridSpec(config)),
    "controller_lab": learning,
    "planned_selection": planned_selection, "planned_test": planned_test,
    "custom_planned": {"selection": model_choice["result"], "test": model_test["result"]},
    "frozen_planned": {"selection": frozen_choice["result"], "test": frozen_test["result"]},
    "policy_journal": {"origin": journal_origin, "spec": asdict(journal_spec),
                       "evaluation": journal_evaluation["data"], "selection": journal_choice["data"]["result"],
                       "test": journal_test["data"]["result"], "history": journal_history},
    "custom_model": {"compare": custom_compare, "study": custom_study, "controller_lab": custom_learning},
    "installed_http_api_matches_direct_calls": api_checks,
    "installed_web_frozen_planned": frozen_web_checks,
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
        for key in ("version", "static_sha256", "compare", "study", "grid_check", "controller_lab", "custom_model", "planned_selection", "planned_test", "custom_planned", "frozen_planned", "policy_journal"):
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
        original_bundle = (chosen / "selection-bundle.json").read_bytes()
        if json.loads(original) != installed["planned_selection"]:
            raise ValueError("installed planned selection CLI differs from API")
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "test",
             str(chosen / "selection-bundle.json"), "--out", str(tested)], base, logs, "installed-planned-test")
        if json.loads((tested / "test.json").read_bytes()) != installed["planned_test"]:
            raise ValueError("installed planned test CLI differs from API")
        if (chosen / "selection.json").read_bytes() != original:
            raise ValueError("planned test changed its input record")
        if (chosen / "selection-bundle.json").read_bytes() != original_bundle:
            raise ValueError("planned test changed its input environment bundle")
        chosen_context = json.loads(original_bundle)["context"]["selection"]
        tested_context = json.loads((tested / "environment.json").read_bytes())["execution"]
        if tested_context["selection"] != chosen_context or tested_context["test"]["state"] != "recorded":
            raise ValueError("installed test did not preserve the original selection environment")
        redrawn = base / "old record redrawn"
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "render",
             str(chosen / "selection.json"), "--out", str(redrawn)], base, logs, "installed-planned-render")
        redraw_context = json.loads((redrawn / "environment.json").read_bytes())
        if redraw_context["execution"]["selection"] != {"state": "not_recorded", "runtime": None}:
            raise ValueError("installed redraw filled an unrecorded old execution environment")
        if (redrawn / "selection.json").read_bytes() != original:
            raise ValueError("installed redraw changed the raw selection result")
        frozen_spec = base / "frozen spec.json"
        frozen_checkpoint = base / "frozen checkpoint.json"
        frozen_spec.write_text(json.dumps(installed["frozen_planned"]["selection"]["spec"]), encoding="utf-8")
        frozen_checkpoint.write_text(json.dumps(installed["frozen_planned"]["selection"]["policy_before"]), encoding="utf-8")
        frozen_choice, frozen_test = base / "frozen choice", base / "frozen test"
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "select", "--spec", str(frozen_spec),
             "--policy-checkpoint", str(frozen_checkpoint), "--out", str(frozen_choice)], base, logs, "installed-frozen-select")
        frozen_original = (frozen_choice / "selection-bundle.json").read_bytes()
        if json.loads((frozen_choice / "selection.json").read_bytes()) != installed["frozen_planned"]["selection"]:
            raise ValueError("installed frozen selection CLI differs from API")
        run([str(python), "-I", "-m", "event_control_lab.planned_study", "test",
             str(frozen_choice / "selection-bundle.json"), "--out", str(frozen_test)], base, logs, "installed-frozen-test")
        if json.loads((frozen_test / "test.json").read_bytes()) != installed["frozen_planned"]["test"]:
            raise ValueError("installed frozen test CLI differs from API")
        if (frozen_choice / "selection-bundle.json").read_bytes() != frozen_original:
            raise ValueError("frozen test modified its original choice")
        if not (frozen_test / "policy-history.json").is_file():
            raise ValueError("frozen test omitted the continuation history")
        journal_input, journal_spec = base / "journal origin.json", base / "journal spec.json"
        journal_input.write_text(json.dumps(installed["policy_journal"]["origin"]), encoding="utf-8")
        journal_spec.write_text(json.dumps(installed["policy_journal"]["spec"]), encoding="utf-8")
        journal_outputs = [base / name for name in ("journal evaluation", "journal choice", "journal test", "journal redraw")]
        journal_commands = [
            ["evaluate", "--policy", str(journal_input), "--seeds", "9001"],
            ["select", "--policy", str(journal_outputs[0]/"policy-history.json"), "--spec", str(journal_spec)],
            ["test", str(journal_outputs[1]/"policy-workflow.json")],
            ["render", str(journal_outputs[2]/"policy-workflow.json")],
        ]
        for index, (command, output) in enumerate(zip(journal_commands, journal_outputs)):
            run([str(python), "-I", "-m", "event_control_lab.policy_journal", *command, "--out", str(output)],
                base, logs, "installed-journal-" + str(index))
        for output, filename, phase in zip(journal_outputs,
                ("evaluation.json", "selection.json", "test.json"), ("evaluation", "selection", "test")):
            if json.loads((output/filename).read_bytes()) != installed["policy_journal"][phase]:
                raise ValueError("journal CLI differs from installed API: " + phase)
        if ((journal_outputs[2]/"policy-workflow.json").read_bytes()
                != (journal_outputs[3]/"policy-workflow.json").read_bytes()):
            raise ValueError("journal redraw changed the original complete workflow")
        extracted = extract_source(archive, base / "fresh source")
        for path in ("README.md", "README.en.md", "BRANDING.md", "START_HERE.md", "quickstart.py", "docs/grid-check.md",
                     "examples/grid-check.json", "examples/own_model_case.py", "docs/own-model.md", "scripts/check_distribution.py", "docs/planned-study.md",
                     "examples/planned-study.json", "event_control_lab/planned_study.py",
                     "event_control_lab/planned_report.py", "event_control_lab/planned_cli.py",
                     "event_control_lab/planned_context.py", "event_control_lab/planned_models.py",
                     "examples/planned_model_case.py", "docs/planned-models.md",
                     "event_control_lab/planned_policy.py", "docs/planned-policy.md", "examples/planned-frozen-policy.json",
                     "event_control_lab/policy_journal.py", "event_control_lab/policy_journal_report.py",
                     "event_control_lab/policy_journal_cli.py", "docs/policy-history.md", "examples/continued-policy-plan.json"):
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
        model_choice_output, model_test_output = base / "model choice", base / "model test"
        run([str(python), "-m", "examples.planned_model_case", "select", "--spec", str(planned_spec),
             "--out", str(model_choice_output)], extracted, logs, "extracted-model-select")
        run([str(python), "-m", "examples.planned_model_case", "test",
             str(model_choice_output / "selection-bundle.json"), "--decay", "0.4", "--gain", "1.2",
             "--out", str(model_test_output)], extracted, logs, "extracted-model-test")
        model_record = json.loads((model_test_output / "test.json").read_text(encoding="utf-8"))
        if (not model_record["test_runs"] or model_record["selection"]["model"]["source_sha256"]
                != hashlib.sha256(model_source.read_bytes()).hexdigest()):
            raise ValueError("extracted planned model case did not preserve source and declared tests")
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
            "installed_planned_context_bundle_and_render": True,
            "installed_custom_model_compare_study_learning_match_source": True,
            "installed_custom_planned_selection_and_test_match_source": True,
            "extracted_local_model_separate_selection_and_test": True,
            "installed_frozen_policy_planned_cli_api_parity": True,
            "frozen_policy_history_and_original_choice_preserved": True,
            "installed_chronological_policy_api_cli_and_redraw": True,
            "installed_web_frozen_planned": installed["installed_web_frozen_planned"],
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
