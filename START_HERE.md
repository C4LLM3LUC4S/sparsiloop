# 第一次使用 / Start here

想回答“最多发这些消息，哪个门槛能满足误差要求？”时，可以先看[先选一个发送方案](docs/planned-study.md)。这个流程先保存候选和选择规则，再用预留条件复核；测试阶段不临时改门槛。

需要 Python 3.10+。下载本仓库的 Code → Download ZIP，**完整解压**，在项目文件夹打开终端：

```powershell
python quickstart.py
```

自动选择空闲本地端口并打开网页，不安装依赖、不联网下载、不修改现有环境。保持终端打开；停止时按 Ctrl+C。浏览器没有弹出时，手动打开打印的本地网址。只绑定 `127.0.0.1`。

直接看 MFAC、ILC、强化学习案例：

```powershell
python quickstart.py --mode controllers
```

自动生成并打开中文 HTML 报告，每次使用新目录。用 `--method ilc` 可只运行一种方法；`--out "path with spaces/new-report"` 可指定一个新目录。已有报告不覆盖。`--no-open` 可用于不打开浏览器的环境。

先看报告里的“从哪里开始看”：

- MFAC 在运行时估计输入对模型的影响，先检查是否跑完，再看误差曲线。
- ILC 反复执行同一个任务，比较前后几轮的误差，看看有没有逐步改善。
- 强化学习先训练，再固定策略测试。看“测试”阶段的结果；训练成绩不能代替测试成绩。

三个案例的条件不同，不能按分数直接排名。报告保留每轮结果和失败原因，完整公式见 [经典控制案例](docs/classic-controllers.md)。

已经训练过，想换几个随机种子再测一次？用 `python -m event_control_lab evaluate-policy runs/controllers/policy-checkpoint.json --seeds 2001,2002 --out runs/new-test`。这里的 `runs/controllers` 要换成你实际保存报告的目录。这次不会重新训练，详见[保存策略再测试](docs/saved-policy.md)。

想换成自己的模型：先运行 `python -m examples.own_model_case --out runs/own-model`，打开新目录中的 `report.html`。报告会带你查看一个简化执行器在减少消息后的表现，再尝试三种控制方法。熟悉流程后，按[模型接入说明](docs/own-model.md)替换示例中的模型。先用已知输入检查计算结果，再比较控制效果。

网页顶部的“运行比较”比较三种**发送策略**。想试 MFAC、ILC 或强化学习，点击页面上的“试试 MFAC、ILC 和强化学习”，选择方法、设置轮数，再点击“运行选中的实验”。两处是独立实验，参数分别设置。

结果中会分开显示训练、ILC 轮次和测试。点击“下载完整报告 ZIP”，完整解压后打开 `report.html`，关闭服务后也能阅读。强化学习还可以另存完整策略；在“保存的策略，拿出来再测一次”中选择这个文件，填写新种子，只测试、不训练。当前页面会记住已用测试种子，下次使用请保存更新后的策略文件。

网页使用内置一阶模型、20 ms 步长和 0.2–2 秒时域，限制每次实验规模。自定义模型、更多参数和更大实验继续使用 Python 接口或命令行。具体说明见[网页实验](docs/web-recipes.md)。

## 没有成功打开时

- 终端说找不到 `quickstart.py`：确认已经完整解压，并进入包含这个文件的项目文件夹。
- 浏览器没有自动打开：复制终端打印的本地网址，或手动打开报告文件。
- 网页提示连接失败：确认启动它的终端仍在运行，再刷新页面。停止程序后，网页不能继续计算。
- 报告目录已存在：用 `--out` 换一个新目录。旧报告不会被覆盖。
- 某次仿真没有跑完：打开报告查看停止时间和错误原因。报告生成成功，不代表其中每次仿真都成功。

## English

With Python 3.10+, extract the full repository and run `python quickstart.py`. It binds an available loopback port before opening your browser. No installation, account or additional dependency is required. Keep the terminal open; Ctrl+C stops the server. For static learning reports, run `python quickstart.py --mode controllers`; `--no-open` disables browser opening. Each report uses a fresh directory. These are explicit source-preview paths, not an installed-wheel claim; regular installation is `python -m pip install .`.
