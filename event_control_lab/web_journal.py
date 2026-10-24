"""Bounded web transport for complete chronological policy workflows."""

import base64
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

from .controller_lab import evaluation_view, records
from .engine import Config
from . import planned_context as context, policy_journal as journal
from .policy_journal_report import export_workflow


POLICY_LIMIT = 2 * 1024 * 1024
REQUEST_LIMIT = 8 * 1024 * 1024


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def pack(workflow, selection=None):
    saved = journal.load_workflow(workflow)
    phase = saved["phase"]
    history = saved["history_after"]
    choice = saved if phase == "selection" else selection
    reusable = _bytes({"checkpoint": history, "seeds": [2**32-1]*5, "keep_history": True}) <= POLICY_LIMIT
    testable = choice is not None and _bytes({"selection": choice, "keep_history": True}) <= REQUEST_LIMIT
    with tempfile.TemporaryDirectory(prefix="sparsiloop-web-journal-") as temporary:
        folder = Path(temporary)/"report"
        export_workflow(saved, folder, recover_on_failure=False)
        if phase == "test":
            (folder/"selection-workflow.json").write_text(
                json.dumps(selection, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        manifest = json.loads((folder/"journal-environment.json").read_text(encoding="utf-8"))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.iterdir()):
                archive.writestr(path.name,path.read_bytes())
    content = buffer.getvalue()
    response = {"workflow": saved, "policy_history": history, "checkpoint": history["checkpoint"],
                "archive_base64": base64.b64encode(content).decode("ascii"),
                "archive_sha256": hashlib.sha256(content).hexdigest(), "web_reusable": reusable,
                "web_testable": testable, "report_runtime": manifest["report_rendering"],
                "continuation_note": "" if reusable and (phase == "evaluation" or testable) else
                "这次结果和完整下载已生成；记录太大，后续请用本地接续命令。已用编号仍保留，不要回到旧历史重试。"}
    if choice is not None:
        response["selection_workflow"] = choice
    if phase == "evaluation":
        rows = []
        for method, stage, label, config, run in records(evaluation_view(saved["data"])):
            rows.append({"method": method, "stage": stage, "trial_or_seed": label,
                         "policy": run["policy"], "status": run["status"],
                         "position_rmse": run["metrics"]["position_rmse"],
                         "duration_completed": run["duration_completed"], "error": run.get("error"),
                         "packets": run["packets"]})
        return response | {"mode": "evaluation", "rows": rows,
                           "specification": saved["data"]["evaluation_config"]}
    data = saved["data"]
    return response | {"mode": phase, "record": data["result"], "context": data["context"],
                       "selection_context": context.selection_bundle(data)["context"]}


def evaluate_from_web(value):
    from .web_recipes import web_config, MAX_INTERVALS

    history = journal.history_for(value["checkpoint"])
    if _bytes(value) > POLICY_LIMIT:
        raise ValueError("完整策略请求超过网页的 2 MiB 限制，请保留文件并用本地命令。")
    config = Config.from_dict(value["config"]) if value.get("config") is not None else Config.from_dict(
        history["checkpoint"]["evaluation_config"])
    web_config(config)
    seeds = value.get("seeds")
    if not isinstance(seeds,list) or not 1 <= len(seeds) <= 5:
        raise ValueError("网页一次可以测试 1–5 个新种子。")
    if len(seeds)*6*config.steps > MAX_INTERVALS:
        raise ValueError("这组测试超过网页的 20000 个区间限制，请减少种子或使用本地命令。")
    return pack(journal.evaluate_saved(history,seeds,config))


def select_from_web(spec, value):
    from .web_planned import web_spec

    web_spec(spec)
    if not isinstance(value,dict) or _bytes(value)>POLICY_LIMIT:
        raise ValueError("网页需要完整策略或历史，文件最多 2 MiB；不会改用其他控制器。")
    if _bytes({"spec":asdict(spec),"policy_checkpoint":value,"keep_history":True})>REQUEST_LIMIT:
        raise ValueError("这组完整请求超过网页的 8 MiB 限制，请使用本地接续命令。")
    return pack(journal.select_plan(spec,value))


def test_from_web(value):
    from .web_planned import web_spec
    from .planned_study import PlannedSpec

    if _bytes({"selection":value,"keep_history":True})>REQUEST_LIMIT:
        raise ValueError("完整选择请求超过网页的 8 MiB 限制，请用本地命令复核；原记录保留。")
    saved=journal.load_workflow(value)
    if saved["phase"]!="selection":
        raise ValueError("复核需要选择阶段的完整记录，不能用测试或评测记录代替。")
    web_spec(PlannedSpec.from_dict(saved["data"]["result"]["spec"]))
    return pack(journal.test_plan(saved),selection=saved)
