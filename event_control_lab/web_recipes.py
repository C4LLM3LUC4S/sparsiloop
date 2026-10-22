"""Bounded web entry points for existing controller recipes; exports are temporary."""

import base64
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

from .controller_lab import (ControllerLabSpec, controller_lab, evaluation_view,
                             export_controller_lab, export_policy_evaluation, records)
from .engine import Config
from .policy import evaluate_policy, load_checkpoint


MAX_INTERVALS = 20000


def error_message(detail):
    if any("\u4e00" <= char <= "\u9fff" for char in detail):
        return detail
    messages = (
        ("Use new seeds", "这些种子里有之前用过的编号。请换一组新的种子。"),
        ("must be disjoint", "训练和测试种子有重复，请分别选两组编号。"),
        ("checksum differs", "策略文件与保存时的摘要对不上。请重新选择原文件，不要手动改摘要。"),
        ("source differs", "当前代码与保存策略时的版本不同。请使用原版本测试，或重新训练后保存策略。"),
        ("policy-checkpoint.json", "请选择完整的 policy-checkpoint.json。旧的原始 Q 表缺少这次测试需要的记录。"),
        ("trained dt", "时间步长与训练时不同，请保留策略原来的时间设置。"),
        ("trained duration", "总时长与训练时不同，请保留策略原来的时间设置。"),
        ("trained input_limit", "输入上限与训练时不同，请保留策略原来的输入范围。"),
        ("budget and delay_steps", "发送上限或延迟步数超过了这次仿真的范围，请调小后再试。"),
        ("full-rate", "训练需要固定间隔的完整测量，并关闭延迟、丢包和噪声。"),
        ("request must contain", "请求为空或文件太大。策略文件最多 2 MiB；更大文件请使用命令行。"),
    )
    for text, message in messages:
        if text in detail:
            return message
    return "这组参数或策略文件还不能运行。请核对方法、时间设置和文件格式；原始错误可以展开查看。"


def web_config(config):
    if config.dt != 0.02 or not 0.2 <= config.duration <= 2:
        raise ValueError("网页目前使用 20 ms 步长、0.2–2 秒时域；其他设置请用命令行。")


def pack(result, evaluation_only=False):
    view = evaluation_view(result) if evaluation_only else result
    rows = []
    for method, stage, label, config, run in records(view):
        rows.append({"method": method, "stage": stage, "trial_or_seed": label,
                     "policy": run["policy"], "status": run["status"],
                     "position_rmse": run["metrics"]["position_rmse"],
                     "duration_completed": run["duration_completed"], "error": run.get("error"),
                     "packets": run["packets"]})
    with tempfile.TemporaryDirectory(prefix="sparsiloop-web-") as temporary:
        output = Path(temporary) / "report"
        if evaluation_only:
            export_policy_evaluation(result, output)
        else:
            export_controller_lab(result, output)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output.iterdir()):
                archive.writestr(path.name, path.read_bytes())
        saved = output / "policy-checkpoint.json"
        checkpoint = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else None
    content = buffer.getvalue()
    return {"mode": "evaluation" if evaluation_only else "recipes", "rows": rows,
            "specification": result.get("specification", result.get("evaluation_config")),
            "checkpoint": checkpoint, "archive_base64": base64.b64encode(content).decode("ascii"),
            "archive_sha256": hashlib.sha256(content).hexdigest(),
            "scope": "All requested runs and failures are retained in the ZIP; not evidence of human benefit"}


def run_recipes(value):
    if not isinstance(value, dict) or set(value) - {"method", "spec"}:
        raise ValueError("请只提供要运行的方法和实验设置；网页不接受 Python 模型或控制器代码。")
    method = value.get("method", "all")
    if method not in ("all", "mfac", "ilc", "rl"):
        raise ValueError("请选择 MFAC、ILC、强化学习或全部方法。")
    spec = ControllerLabSpec.from_dict(value.get("spec", {}))
    web_config(spec.config)
    if len(spec.evaluation_seeds) > 5 or len(spec.training_seeds) > 128 or spec.ilc_trials > 30:
        raise ValueError("网页最多支持 128 个训练种子、5 个测试种子和 30 轮 ILC；更大实验请用命令行。")
    count = (int(method in ("all", "mfac"))
             + (spec.ilc_trials if method in ("all", "ilc") else 0)
             + (len(spec.training_seeds) + 9 * len(spec.evaluation_seeds) if method in ("all", "rl") else 0))
    if count * spec.config.steps > MAX_INTERVALS:
        raise ValueError("这组实验超过网页的 20000 个仿真区间限制，请减少轮数、种子或时长。")
    return pack(controller_lab(spec, method))


def test_saved_policy(value):
    if not isinstance(value, dict) or set(value) - {"checkpoint", "seeds", "config"} or "checkpoint" not in value:
        raise ValueError("请选择完整的 policy-checkpoint.json，并填写新的测试种子。")
    _, _, base = load_checkpoint(value["checkpoint"])
    if value.get("config") is not None:
        base = Config.from_dict(value["config"])
    web_config(base)
    seeds = value.get("seeds")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 5:
        raise ValueError("网页一次可以测试 1–5 个新种子。")
    if len(seeds) * 6 * base.steps > MAX_INTERVALS:
        raise ValueError("这组测试过大，请减少种子或使用命令行。")
    return pack(evaluate_policy(value["checkpoint"], seeds, base), evaluation_only=True)


def default_specification():
    value = asdict(ControllerLabSpec())
    value["training_seeds"] = list(range(100, 132))
    return value
