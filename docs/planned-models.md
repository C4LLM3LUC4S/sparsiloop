# 用自己的模型选发送方案，再按原计划复核

已经把模型接到 `compare`，还想知道“同一个对象，在消息上限内该用哪个发送门槛”？现在可以把同一份 `PlantAdapter` 传给本地选择和复核接口。先选方案，再保存记录；下次重新构建原模型，用原先预留的种子复核。这里仍使用固定反馈，不训练控制器。

网页继续只运行两种内置对象。自己的 Python 模型只在本地运行，不上传到网页，也不会从 JSON 中自动导入代码。

## 先用现有执行器例子走一遍

在完整源码目录运行。两步使用同一个公开的一阶执行器，模型实现仍在 `examples/own_model_case.py`，没有换成内置一阶方程：

```powershell
python -m examples.planned_model_case select --spec examples/planned-study.json --decay 0.4 --gain 1.2 --out runs/model-choice
python -m examples.planned_model_case test runs/model-choice/selection-bundle.json --decay 0.4 --gain 1.2 --out runs/model-test
```

先打开 `runs/model-choice/report.html`。它保留所有候选，告诉你有没有方案满足要求；选择阶段不会运行测试种子。再打开 `runs/model-test/report.html`，核对每次是否跑完、首个状态的 RMSE 是否达标、实际发送了多少条。测试不重新选门槛，也不按事件方案的实际消息数改周期对照的预算。没有合格候选时，不运行测试。

第二条命令必须明确填写原模型参数。改成 `--gain 1.3` 会在运行前拒绝，不会悄悄改用内置模型。输出用新目录，旧记录不会覆盖。例子使用简化模型，没有实物标定；它是流程演示，不证明独立测试、真实采用或硬件收益。

如果输出目录已存在，或它的上级路径实际是一个文件，命令会在读取输入、构建模型和计算前拒绝。保留原文件，换一个新的目录路径，再用原方案或原选择重试；不用改参数或换掉预留编号。这项提前检查不保证之后磁盘空间和写入权限一直可用，保存过程中仍按实际错误与恢复提示处理。

## 换成你的模型

先按[模型接口](own-model.md)构建 `PlantAdapter`。用于这个流程时，`source_sha256` 必须填写：对你保留的模型实现计算摘要，并把实际参数、状态单位和输入单位写进声明。摘要由你负责核对，工具不会认证声明与代码相符，也不会自动打包私有源码或依赖。

下面是在上述公开例子上可直接运行的 Python 版本。换自己的模型时，只替换模型构建处；方案、记录和复核仍走同一条接口：

```python
import json
from pathlib import Path
from examples.own_model_case import actuator_model
from event_control_lab.planned_study import PlannedSpec
from event_control_lab.planned_context import (
    select_with_context, test_with_context, export_bundle,
)

spec = PlannedSpec.from_dict(json.loads(Path("examples/planned-study.json").read_text("utf-8")))
model = actuator_model(decay=0.4, gain=1.2)
selected = select_with_context(spec, plant=model)
export_bundle(selected, "runs/python-model-choice")

# 以后重新打开程序时，显式构建同一模型，再读取保存的记录。
saved = json.loads(Path("runs/python-model-choice/selection-bundle.json").read_text("utf-8"))
same_model = actuator_model(decay=0.4, gain=1.2)
tested = test_with_context(saved, plant=same_model)
export_bundle(tested, "runs/python-model-test")
```

每条运行都会调用模型工厂，重置由你实现的内部状态。工厂收到该条运行的完整配置；请用冻结的声明参数定义动力学，不要因候选门槛或通信条件不同而暗中换对象。额外记忆、随机流、依赖和参数来源也由你保留；核心随机输入相同不代表模型内部随机性已对齐。

## 保存什么，怎样判断出了问题

选择记录包保留模型声明、全部选择轨迹、原规则与预留测试编号；测试记录还嵌入完整选择。报告目录另存 `model.json`、原始 JSON、运行 CSV、全部轨迹、环境信息和可复用记录包。控制器只使用到达观测；每次实际模型初始化配置、模型错误和失败前缀也保留。

| 看到什么 | 接下来做什么 |
| --- | --- |
| 提示需要 `plant=模型` | 回到原本地程序重新构建模型。JSON 只有声明和结果，没有可执行代码；不要换成不带模型的内置流程。 |
| 参数、单位或来源不匹配 | 找回选择时的代码、参数和依赖；保留原记录。不要手改记录或补写摘要。确实要换模型，就另定方案并保存到新目录。 |
| 模型初始化或更新失败 | 查看原始 `error`，先核模型工厂、状态维数、数值和单位。失败记录和 `null` 留着，不能当作零误差或便宜的完整任务。 |
| 复核没有通过 | 原选择仍保留。若根据这些结果调参，这批数据就是开发记录，后续另定方案；不要用测试结果临时改选。 |

误差考察首个状态相对零目标的完整时段 RMSE，单位沿用声明。原始 JSON/CSV 的技术字段仍叫 `position_rmse`；对自定义模型，它表示第一个状态分量，不自动表示米，也不跨单位或尺度比较。第二个状态只在位置—速度布局中参与反馈。单输入、标量或位置—速度布局的限制保持不变；任意观测、多输入和非零参考尚未接入。

## 旧记录与只重绘报告

自定义对象采用独立的模型选择记录格式，内置对象原有 v1 格式和数值身份没有改写。加载时核对模型的完整声明和计算源码摘要；缺失或不匹配会在仿真前拒绝。报告和终端文案不进入计算身份。请保留生成记录时的源码包及其原始字节，不能把“不报错”当来源认证。

只想重新打开结果，不必重新构建模型或运行种子：

```powershell
python -m event_control_lab.planned_study render runs/model-test/test-bundle.json --out runs/model-redrawn
```

选择、测试和这次出报告的环境仍分开保存。旧原始记录没写环境，就继续保留未知，不用当前电脑补历史。种子编号分开、相同环境或相同摘要都不证明统计独立、预注册、稳定性或跨平台浮点逐位一致。

## English

Reuse an explicit local `PlantAdapter` with `select_with_context(spec, plant=model)` and `test_with_context(saved, plant=model)`. Testing requires a matching model declaration, parameters, units and declared source digest; JSON never imports code or falls back to a built-in plant. Every run receives a fresh factory call and records its initialization configuration and failures.

The existing built-in selection format remains separate and unchanged. A new local-model format preserves the fixed selection rule, declared seed split, common packet cap, complete raw records and separate execution environments. Only fixed feedback and zero-target first-state RMSE are supported here; this does not add joint controller training/selection/testing or arbitrary observations. The source-only actuator commands above demonstrate separate processes, not independent adoption or model certification.
