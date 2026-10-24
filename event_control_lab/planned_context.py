"""Execution metadata outside the unchanged numerical records and source identity."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import platform
from pathlib import Path
import re
import struct
import sys

from . import __version__
from .planned_study import FORMAT as SELECTION_FORMAT, digest, select_schedule, test_schedule
from .planned_models import FORMAT as MODEL_SELECTION_FORMAT, TEST_FORMAT as MODEL_TEST_FORMAT
from .planned_policy import FORMAT as POLICY_SELECTION_FORMAT, TEST_FORMAT as POLICY_TEST_FORMAT
from .export_recovery import recovery_record


BUNDLE_FORMAT = "sparsiloop-planned-bundle-v1"
CONTEXT_FORMAT = "sparsiloop-planned-context-v1"
RUNTIME_FIELDS = {"python_implementation", "python_version", "os_family", "python_pointer_bits",
                  "sparsiloop_version", "float_radix", "float_mantissa_bits", "captured_at_utc"}


def runtime_info():
    """Public execution facts only: no hostnames, paths, environment variables or packages."""
    return {"python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "os_family": {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}.get(sys.platform, sys.platform),
            "python_pointer_bits": struct.calcsize("P") * 8, "sparsiloop_version": __version__,
            "float_radix": sys.float_info.radix, "float_mantissa_bits": sys.float_info.mant_dig,
            "captured_at_utc": datetime.now(timezone.utc).isoformat()}


def phase_of(result):
    if isinstance(result, dict):
        if result.get("format") in (SELECTION_FORMAT, MODEL_SELECTION_FORMAT, POLICY_SELECTION_FORMAT):
            return "selection"
        if result.get("analysis") in ("planned-budget-test-v1", MODEL_TEST_FORMAT, POLICY_TEST_FORMAT):
            return "test"
    raise ValueError("请选择完整的选择记录、测试记录或带环境的记录包；实验方案不能代替结果。")


def entry(state, runtime=None):
    return {"state": state, "runtime": deepcopy(runtime)}


def context_for(result, selection=None, testing=None):
    phase = phase_of(result)
    context = {"format": CONTEXT_FORMAT, "phase": phase, "result_sha256": digest(result),
               "selection": deepcopy(selection) if selection is not None else entry("not_recorded"),
               "test": deepcopy(testing) if testing is not None else
               entry("not_requested" if phase == "selection" else
                     "not_recorded" if result.get("test_runs") else "not_run")}
    context["context_sha256"] = digest(context)
    return context


def validate_runtime(runtime):
    if not isinstance(runtime, dict) or set(runtime) != RUNTIME_FIELDS:
        raise ValueError("运行环境字段不完整或含额外信息，请使用程序保存的原记录包。")
    for name in RUNTIME_FIELDS - {"python_pointer_bits", "float_radix", "float_mantissa_bits", "captured_at_utc"}:
        value = runtime[name]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_. +\-]{1,80}", value):
            raise ValueError("运行环境的版本或系统字段格式不正确，请使用原记录包。")
    for name in ("python_pointer_bits", "float_radix", "float_mantissa_bits"):
        if type(runtime[name]) is not int or not 1 <= runtime[name] <= 1024:
            raise ValueError("运行环境的浮点信息格式不正确。")
    stamp = runtime["captured_at_utc"]
    if not isinstance(stamp, str) or len(stamp) > 48:
        raise ValueError("运行环境的时间格式不正确。")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("运行环境的时间格式不正确。") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("运行环境时间需要使用 UTC。")


def validate_context(context, result):
    fields = {"format", "phase", "result_sha256", "selection", "test", "context_sha256"}
    if not isinstance(context, dict) or set(context) != fields or context["format"] != CONTEXT_FORMAT:
        raise ValueError("环境记录格式不正确，请使用程序保存的完整记录包。")
    if context["context_sha256"] != digest({k: v for k, v in context.items() if k != "context_sha256"}):
        raise ValueError("环境记录与保存时的摘要不一致，请使用原记录包，不要手动补摘要。")
    phase = phase_of(result)
    if context["phase"] != phase or context["result_sha256"] != digest(result):
        raise ValueError("运行环境不属于这份结果，请把原结果和环境一起载入。")
    for stage in ("selection", "test"):
        value = context[stage]
        if not isinstance(value, dict) or set(value) != {"state", "runtime"}:
            raise ValueError("环境记录不完整，请使用原记录包。")
        allowed = {"recorded", "not_recorded"}
        if stage == "test":
            if phase == "selection":
                allowed = {"not_requested"}
            elif not result.get("test_runs"):
                allowed = {"not_run"}
        if not isinstance(value["state"], str) or value["state"] not in allowed:
            raise ValueError("环境记录的阶段与实际运行不一致。")
        if value["state"] == "recorded":
            validate_runtime(value["runtime"])
        elif value["runtime"] is not None:
            raise ValueError("没有记录或没有运行的阶段不能补上当前环境。")
    return context


def as_bundle(value):
    if isinstance(value, dict) and value.get("format") == BUNDLE_FORMAT:
        if set(value) != {"format", "result", "context"}:
            raise ValueError("记录包含不支持的字段，请选择原文件。")
        validate_context(value["context"], value["result"])
        return value
    phase_of(value)
    return {"format": BUNDLE_FORMAT, "result": value, "context": context_for(value)}


def select_with_context(spec, *, plant=None, policy_checkpoint=None):
    if plant is not None and policy_checkpoint is not None:
        raise ValueError("这条冻结策略流程先使用内置标量对象，不能同时换成本地模型。")
    runtime = runtime_info()
    if policy_checkpoint is not None:
        from .planned_policy import select_policy_schedule
        result = select_policy_schedule(spec, policy_checkpoint=policy_checkpoint)
    elif plant is None:
        result = select_schedule(spec)
    else:
        from .planned_models import select_model_schedule
        result = select_model_schedule(spec, plant=plant)
    return {"format": BUNDLE_FORMAT, "result": result,
            "context": context_for(result, selection=entry("recorded", runtime))}


def test_with_context(value, *, plant=None):
    saved = as_bundle(value)
    if saved["context"]["phase"] != "selection":
        raise ValueError("复核需要 selection-bundle.json 或 selection.json，测试记录不能代替选择。")
    runtime = runtime_info()
    if saved["result"].get("format") == POLICY_SELECTION_FORMAT:
        if plant is not None:
            raise ValueError("这份选择记录使用内置标量对象和保存的冻结策略，复核时不能更换模型。")
        from .planned_policy import test_policy_schedule
        result = test_policy_schedule(saved["result"])
    elif saved["result"].get("format") == MODEL_SELECTION_FORMAT:
        from .planned_models import test_model_schedule
        result = test_model_schedule(saved["result"], plant=plant)
    else:
        if plant is not None:
            raise ValueError("这份记录使用内置模型，不能在复核时换成自己的模型；请另存一份新选择方案。")
        result = test_schedule(saved["result"])
    return {"format": BUNDLE_FORMAT, "result": result,
            "context": context_for(result, selection=saved["context"]["selection"],
                                   testing=entry("recorded", runtime) if result["test_runs"] else entry("not_run"))}


def selection_bundle(value):
    saved = as_bundle(value)
    if saved["context"]["phase"] == "selection":
        return saved
    result = saved["result"]["selection"]
    return {"format": BUNDLE_FORMAT, "result": result,
            "context": context_for(result, selection=saved["context"]["selection"])}


def export_bundle(value, destination, input_hash=None, *, recover_on_failure=True):
    """Render without rerunning; unrecorded execution environments remain unknown."""
    from .planned_report import export_selection, export_test, write_json

    saved = as_bundle(value)
    manifest = {"format": "sparsiloop-planned-report-environment-v1",
                "execution": deepcopy(saved["context"]), "report_rendering": runtime_info(),
                "scope": "Self-recorded execution facts, bound by checksums; not authenticated provenance or cross-platform bitwise parity"}
    testing = saved["context"]["phase"] == "test"
    with recovery_record(saved, destination, "planned", enabled=recover_on_failure):
        (export_test if testing else export_selection)(saved["result"], destination, input_hash, environment=manifest)
        folder = Path(destination)
        write_json(folder / "environment.json", manifest)
        write_json(folder / "selection-bundle.json", selection_bundle(saved))
        if testing:
            write_json(folder / "test-bundle.json", saved)
    return manifest
