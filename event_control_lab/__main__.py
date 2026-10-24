import argparse
import csv
import json
from pathlib import Path
import sys

from . import __version__
from .engine import Config, compare
from .grid import GridSpec, export_grid_check, grid_check
from .server import serve
from .study import StudySpec, export_study, study
from .controller_lab import ControllerLabSpec, controller_lab, export_controller_lab


def export(result, destination):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (destination / "trajectory.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["policy", "t_s", "position", "velocity", "input", "seen_position",
                         "observation_age_s", "sent", "dropped", "delivered"])
        for run in result["runs"]:
            for row in run["trajectory"]:
                state, seen = row["state"], row["controller_values"]
                writer.writerow([run["policy"], row["t"], state[0], state[1] if len(state) > 1 else "",
                                 row["input"], seen[0] if seen is not None else "",
                                 row["observation_age"], int(row["sent"]), int(row["dropped"]), row["delivered"]])


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="SparsiLoop — local communication experiments")
    parser.add_argument("--version", action="version", version=f"SparsiLoop {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    ui = sub.add_parser("serve", help="open a local browser interface")
    ui.add_argument("--port", type=int, default=8788)
    run = sub.add_parser("compare", help="save one reproducible three-policy comparison")
    run.add_argument("--config", type=Path)
    run.add_argument("--out", type=Path, required=True)
    scan = sub.add_parser("study", help="scan thresholds and construct post-hoc equal-attempt references")
    scan.add_argument("--spec", type=Path, required=True)
    scan.add_argument("--out", type=Path, required=True)
    grid = sub.add_parser("grid-check", help="check deterministic nested grids at fixed physical schedules")
    grid.add_argument("--spec", type=Path, required=True)
    grid.add_argument("--out", type=Path, required=True)
    controllers = sub.add_parser("controller-lab", help="MFAC, repeated-trial ILC and train/freeze/evaluate RL")
    controllers.add_argument("--method", choices=("all", "mfac", "ilc", "rl"), default="all")
    controllers.add_argument("--spec", type=Path)
    controllers.add_argument("--out", type=Path, required=True)
    policy = sub.add_parser("evaluate-policy", help="test a saved policy on new seeds, without training")
    policy.add_argument("checkpoint", type=Path)
    policy.add_argument("--seeds", required=True, help="comma-separated new integer seeds")
    policy.add_argument("--config", type=Path)
    policy.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command != "serve" and (arguments.out.exists() or arguments.out.is_symlink()):
            raise ValueError(
                "输出路径已存在，这次没有开始计算；请换一个新目录，旧结果会保留。 / "
                "output directory already exists; choose a new --out path"
            )
        if arguments.command == "serve":
            if not 0 <= arguments.port <= 65535:
                raise ValueError("port must be between 0 and 65535")
            serve(arguments.port)
        elif arguments.command == "evaluate-policy":
            from .policy import evaluate_policy, export_evaluation, read_checkpoint
            from .policy_files import load_standalone_checkpoint

            value, digest = read_checkpoint(arguments.checkpoint)
            load_standalone_checkpoint(value)
            config = Config.from_dict(json.loads(arguments.config.read_text(encoding="utf-8-sig"))) if arguments.config else None
            seeds = [int(part.strip()) for part in arguments.seeds.split(",")]
            result = evaluate_policy(value, seeds, config)
            result["checkpoint_file_sha256"] = digest
            export_evaluation(result, arguments.out)
            print("评测已保存；这次没有重新训练。 / Evaluation saved; no training.")
            print(str((arguments.out / "report.html").resolve()))
        elif arguments.command == "controller-lab":
            spec = ControllerLabSpec.from_dict(json.loads(arguments.spec.read_text(encoding="utf-8-sig"))) if arguments.spec else ControllerLabSpec()
            result = controller_lab(spec, arguments.method)
            export_controller_lab(result, arguments.out)
            print(json.dumps({"output": str(arguments.out.resolve()), "methods": list(result["cases"]),
                              "report": str((arguments.out / "report.html").resolve())}, indent=2))
        elif arguments.command == "grid-check":
            spec = GridSpec.from_dict(json.loads(arguments.spec.read_text(encoding="utf-8-sig")))
            result = grid_check(spec)
            export_grid_check(result, arguments.out)
            print(json.dumps({"output": str(arguments.out.resolve()), "analysis": result["analysis"],
                              "summaries": result["summaries"],
                              "changes_from_finest": result["changes_from_finest"]}, indent=2))
        elif arguments.command == "study":
            spec = StudySpec.from_dict(json.loads(arguments.spec.read_text(encoding="utf-8-sig")))
            result = study(spec)
            export_study(result, arguments.out)
            print(json.dumps({"output": str(arguments.out.resolve()), "analysis": result["analysis"],
                              "pairs": len(result["pairs"]), "summaries": result["summaries"]}, indent=2))
        else:
            config = Config.from_dict(json.loads(arguments.config.read_text(encoding="utf-8"))) if arguments.config else Config()
            result = compare(config)
            export(result, arguments.out)
            print(json.dumps({"output": str(arguments.out.resolve()), "protocol": result["protocol"],
                              "runs": [{"policy": run["policy"], "status": run["status"],
                                        "position_rmse": run["metrics"]["position_rmse"],
                                        "packets": run["packets"]} for run in result["runs"]]}, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"event-control-lab: {exc}\n")


if __name__ == "__main__":
    main()
