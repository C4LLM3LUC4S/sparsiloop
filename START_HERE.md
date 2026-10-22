# 第一次使用 / Start here

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

想换成自己的模型：先运行 `python -m examples.own_model_case --out runs/own-model`，打开新目录中的 `report.html`。报告会带你查看一个简化执行器在减少消息后的表现，再尝试三种控制方法。熟悉流程后，按[模型接入说明](docs/own-model.md)替换示例中的模型。先用已知输入检查计算结果，再比较控制效果。

网页上的“运行比较”只比较三种**发送策略**；MFAC、ILC 和强化学习目前从上面的命令进入。两者是不同的实验入口。

## 没有成功打开时

- 终端说找不到 `quickstart.py`：确认已经完整解压，并进入包含这个文件的项目文件夹。
- 浏览器没有自动打开：复制终端打印的本地网址，或手动打开报告文件。
- 网页提示连接失败：确认启动它的终端仍在运行，再刷新页面。停止程序后，网页不能继续计算。
- 报告目录已存在：用 `--out` 换一个新目录。旧报告不会被覆盖。
- 某次仿真没有跑完：打开报告查看停止时间和错误原因。报告生成成功，不代表其中每次仿真都成功。

## English

With Python 3.10+, extract the full repository and run `python quickstart.py`. It binds an available loopback port before opening your browser. No installation, account or additional dependency is required. Keep the terminal open; Ctrl+C stops the server. For static learning reports, run `python quickstart.py --mode controllers`; `--no-open` disables browser opening. Each report uses a fresh directory. These are explicit source-preview paths, not an installed-wheel claim; regular installation is `python -m pip install .`.
