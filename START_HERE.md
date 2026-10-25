# 第一次使用 / Start here

第一次用，可以先打开网页，看少发一些消息会怎样影响控制结果。已经有具体任务的话，下面也列了对应入口。

当前版本是 **0.1.0a6 alpha**。需要 Python 3.10+。首次使用建议下载[完整离线包](https://github.com/C4LLM3LUC4S/sparsiloop/releases/download/v0.1.0a6/SparsiLoop-0.1.0a6.zip)，完整解压后先按包内顶层 `START_HERE.md` 安装；[发行说明和校验](https://github.com/C4LLM3LUC4S/sparsiloop/releases/tag/v0.1.0a6)列出全部文件。

使用源码入口时，进入离线包的 `source/`，或将本仓库的 Code → Download ZIP **完整解压**，在含有 `quickstart.py` 的项目文件夹打开终端：

```powershell
python quickstart.py
```

自动选择空闲本地端口并打开网页，不安装依赖、不联网下载、不修改现有环境。保持终端打开；停止时按 Ctrl+C。浏览器没有弹出时，手动打开打印的本地网址。只绑定 `127.0.0.1`。

## 打开网页后，先做哪件事？

| 你想做的事 | 从哪里开始 |
| --- | --- |
| 看少发消息会有什么影响 | 页面顶部“运行比较”，先改消息上限，再看误差和实际发送次数 |
| 试 MFAC、ILC 或强化学习 | “试试 MFAC、ILC 和强化学习”，选一种方法后运行；参数与顶部比较分别设置 |
| 在消息上限内选一个门槛，再复核 | “先选发送方案，再复核”，先定条件和候选，只运行选择阶段，再按原计划复核 |
| 已有保存的 Q 策略，想换几组条件再测 | “保存的策略，拿出来再测一次”，载入完整文件、填新编号，只测试、不训练 |

“运行比较”改变的是**什么时候发送测量**，不是训练新的控制器。选发送方案时，相同消息上限也不代表实际发送次数相同；结果要结合误差和消息数一起看。[选择与复核说明](docs/planned-study.md)会带你保存全部候选，再用事先预留的条件复核，测试时不临时换门槛。

先别把网页各处的范围混在一起：

- MFAC、ILC、强化学习案例和单独策略测试使用一阶教学模型，每步 20 ms、每次 0.2–2 秒。
- 选择与复核也每步 20 ms，每次可设 0.2–8 秒。固定反馈支持一阶和位置—速度两种内置模型；保存的 Q 策略目前只支持一阶模型，并沿用训练时的时长和输入上限，不会自动扩展到 8 秒。
- 网页任务有规模限制；自定义模型或其他时间设置使用已有 Python/命令行接口。各流程的具体限制见[网页实验](docs/web-recipes.md)。

## 结果怎么看，离开前保存什么？

先看这次有没有完整结束，再看误差和实际消息数。选择报告里的“是哪次运行没满足要求？”按原候选和编号列出超标、未完整结束或无法判断的原因；展开后再决定下一步，不用从汇总分数猜。“报告已生成”不代表每次运行都成功，也不代表都达到原要求。选择阶段还没运行预留测试；强化学习训练成绩也不能代替测试成绩。

点击当前结果的“下载完整报告 ZIP”，完整解压后打开 `report.html`，停止本地服务后仍能阅读。想下次接着做，请再保存对应文件：

| 下一步要做什么 | 保存什么 |
| --- | --- |
| 第一次训练完，之后只测试这个策略 | “保存策略，下次开始测试”得到的 `policy-checkpoint.json` |
| 接着已有评测、选择和复核做新任务 | 页面保留的最新 `policy-history.json`；待复核计划要先完成 |
| 刚选完方案，关掉网页后再按原计划复核 | “保存选择记录，下次按原计划复核”得到的完整选择文件，同时保留选择阶段 ZIP |

完整历史不能代替原选择记录。沿用完整历史的 Q 策略时，网页另存的选择记录叫 `selection-workflow.json`，选择 ZIP 中则叫 `policy-workflow.json`；固定反馈流程保存的是 `selection-bundle.json`。载入时按原文件类型继续，不要手动改摘要。具体文件位置见[跨流程接续说明](docs/policy-history.md)。

重新打开网页后，第一次测试载入完整策略，后续接着做则载入最新完整历史，或点击“使用本页最新的策略与历史”。种子是这组随机数的编号。另开单独测试或新计划时换新编号，原计划复核仍用预留编号；“查看已用种子”列出当前文件已经记下的编号。页面不能自动找回其他设备或副本中的历史。

## 想直接生成控制案例报告？

也可以不用网页表单，运行：

```powershell
python quickstart.py --mode controllers
```

自动生成并打开中文 HTML 报告，每次使用新目录。用 `--method ilc` 可只运行一种方法；`--out "path with spaces/new-report"` 可指定一个新目录。已有报告不覆盖。`--no-open` 可用于不打开浏览器的环境。

先看报告里的“从哪里开始看”：

- MFAC 在运行时估计输入对模型的影响，先检查是否跑完，再看误差曲线。
- ILC 反复执行同一个任务，比较前后几轮的误差，看看有没有逐步改善。
- 强化学习先训练，再固定策略测试。看“测试”阶段的结果；训练成绩不能代替测试成绩。

三个案例的条件不同，不能按分数直接排名。报告保留每轮结果和失败原因，完整公式见 [经典控制案例](docs/classic-controllers.md)。

已经有完整策略，想用命令行只测试、不训练，见[保存策略再测试](docs/saved-policy.md)；已有跨阶段完整历史时，使用[接续命令](docs/policy-history.md)，保留原来的阶段顺序。

想换成自己的模型：先运行 `python -m examples.own_model_case --out runs/own-model`，打开新目录中的 `report.html`。报告会带你查看一个简化执行器在减少消息后的表现，再尝试三种控制方法。熟悉流程后，按[模型接入说明](docs/own-model.md)替换示例中的模型。先用已知输入检查计算结果，再比较控制效果。

独立评测的本地报告末尾会分清：直接看旧结果、用完整 `evaluation.json` 只重绘报告，或用更新后的 checkpoint 另测未用过的编号。后者会产生新测试；checkpoint 不能代替完整阶段历史。

想把这次结果留到以后，除了完整报告和最新历史，也保存对应的发行 ZIP。具体哪些文件用于复核、接续或只重绘，见[旧文件与源码恢复](docs/source-recovery.md)。

## 没有成功打开时

- 终端说找不到 `quickstart.py`：确认已经完整解压，并进入包含这个文件的项目文件夹。
- 浏览器没有自动打开：复制终端打印的本地网址，或手动打开报告文件。
- 网页提示连接失败：确认启动它的终端仍在运行，再刷新页面。停止程序后，网页不能继续计算。
- 输出路径已存在，或上级路径不是文件夹：命令行和源码包里的 `examples.planned_model_case` 示例会在读取输入、构建模型和计算前停下。用 `--out` 换一个保存位置再试，旧文件和报告会保留。
- 某次仿真没有跑完：打开报告查看停止时间和错误原因。报告生成成功，不代表其中每次仿真都成功。
- 本地选择、复核或独立评测算完后保存失败：如果终端给出完整恢复文件，先保留它，再按打印的命令重绘到新目录，不用重跑实验。具体见[保存中断后的恢复](docs/source-recovery.md#算完了报告却没能保存完整)。

## English

For version **0.1.0a6 alpha**, download the [complete offline bundle](https://github.com/C4LLM3LUC4S/sparsiloop/releases/download/v0.1.0a6/SparsiLoop-0.1.0a6.zip) and follow its top-level `START_HERE.md`. For a source preview with Python 3.10+, enter the bundle's `source/` directory or extract the full repository and run `python quickstart.py`. It binds an available loopback port before opening your browser. No installation, account or additional dependency is required. Keep the terminal open; Ctrl+C stops the server. The top comparison changes measurement-sending rules. The controller section runs MFAC, ILC and Q-learning separately; the planned section first selects a sending schedule and then tests the saved choice under the reserved conditions.

Controller recipes and standalone policy tests use the scalar teaching model, 20 ms steps and 0.2–2 s horizons. Planned tasks use 20 ms steps and allow 0.2–8 s: fixed feedback supports both built-in models, while frozen Q policies remain scalar and retain their trained horizon and input limit. These ranges do not change an existing checkpoint or override the workload limits. See [web workflows](docs/web-recipes.md).

Before closing the page, save the full report ZIP. For the first policy test, keep the full `policy-checkpoint.json`; for subsequent tasks, keep the latest complete `policy-history.json`. Finish a pending plan with its original choice, not with the history alone. A web-saved history-workflow choice is `selection-workflow.json`; inside a selection ZIP it is `policy-workflow.json`. Fixed-feedback choices use `selection-bundle.json`. See [file purposes and continuation](docs/policy-history.md). Failed runs remain in the reports; a generated report is not evidence that every requirement was met.

For static learning reports, run `python quickstart.py --mode controllers`; `--no-open` disables browser opening and every report uses a new directory. To use your own model, follow [the model guide](docs/own-model.md). The source entry runs without installing the package; regular package installation is `python -m pip install .`.

If a command's output path already exists or a parent path is a file, it stops before starting a new experiment. Choose a new `--out` directory under a folder and retry; existing files and results stay unchanged.

If a local planned/history or standalone-evaluation report fails during saving and prints a retained complete record, keep it and run the printed redraw command in a working location. Redraw does not repeat training, selection or testing. If the initial recovery copy could not be written or read back, no complete backup is promised. See [save-failure recovery](docs/source-recovery.md#算完了报告却没能保存完整). This local recovery does not provide browser-download recovery.

Local standalone reports distinguish reading saved HTML, redrawing the complete `evaluation.json` without new computation, and using the updated checkpoint for a new test with unused IDs. Keep any separate complete phase history; a checkpoint does not replace or merge it.

The source-only `examples.planned_model_case` selection/test driver also rejects an occupied output or file-valued parent before input reads or model construction. Keep the original plan and reserved IDs, choose a fresh output path, and retry; this is a source-example fix, not a new wheel algorithm.
