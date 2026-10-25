# 接入真实的公开 PID 库 / A pinned controller integration

本例把 [simple-pid 2.0.1](https://pypi.org/project/simple-pid/2.0.1/) 接入到达观测接口，解决一个实际适配障碍：库的默认时钟与采样门针对实时循环，快速仿真循环不能直接把它们当作仿真时间。上游允许显式 `dt` 和自定义 `time_fn`，实现与 API 见 [固定版本源码](https://github.com/m-lundberg/simple-pid/blob/v2.0.1/simple_pid/pid.py)。这是接入方式的调整，不是上游库错误。

本例源于公开软件的接口与时钟约定，不复制私人控制算法。simple-pid 由 Martin Lundberg 维护，使用 [MIT 许可](https://github.com/m-lundberg/simple-pid/blob/v2.0.1/LICENSE.md)。依赖由用户另外安装；没有把其实现复制进核心包。当前只核验 2.0.1，requirements 固定版本及官方 wheel 的 SHA256；其他版本会明确拒绝。

## 从源码目录运行

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r examples/requirements-simple-pid.txt
.\.venv\Scripts\python.exe -m examples.simple_pid_case --out runs/pid-first
```

macOS/Linux 使用 `.venv/bin/python` 替换最后两行的解释器路径。源码目录中已有 `event_control_lab`，不需要先构建核心包；本例不是单独安装 wheel 后自带的命令。核心的默认运行与基础检查仍不需要这个第三方库。

修改对象或链路时，可加 `--config examples/default.json`，并在自己的配置副本中设置 `plant`。用 `--ki 0.1 --kd 0.05` 明确 PID 增益；比例增益来自配置的 `kp`，配置的 `kd` 只供内置控制器使用。输出中的 `actual_gains` 才是本例实际增益。缺依赖时按错误提示安装精确版本。保存位置已经存在，或上级路径是文件时，源码命令会在读取配置和开始计算前停下。先保留原文件，再把 `--out` 换成新目录；配置和增益照旧，不必为了修路径改变实验条件。提前检查不能保证后续磁盘空间和权限一直可用。

## 时序和信息边界

- 每种策略创建全新的有状态 PID，不在策略或重复运行间复用积分状态。
- 只在收到消息时调用；读取收到的位置和两个时间戳，不读取当前真值、真实速度或丢失消息。二阶对象的 D 项由收到的位置差估计，不是速度真值反馈。
- 时钟为仿真的到达时间。库的 `sample_time=None` 关闭第二层采样门；后续 `dt` 是相邻到达的时间差，不是固定网格宽度，也不是程序耗时。
- 第一条观测只初始化 P 项，I 与 D 为零；不为未观测的过去积分。实现先用 `Ki=0` 调用一次，再设置请求 Ki。首次调用的占位 `dt=config.dt` 不产生 I/D；导出中的首个有效到达间隔仍为 `null`。
- PID 内部使用显式输出上限与积分限幅，执行器仍保留核心限幅。核心的 `saturated_updates` 只统计下游执行器，不统计 PID 内部限幅；应结合导出的 P/I/D 和输出复核。
- 到达时间不递增、非因果时间戳或维度不符会产生明确错误。Python 接口没有对恶意控制器提供沙箱隔离。

## 复核输出

`result.json` 与 `trajectory.csv` 保持核心比较格式；新增 `controller.json` 保存依赖版本、实际已安装源码指纹、适配器源码指纹、实际增益、初始化规则和每次收到观测后的 P/I/D 与输出。上游标签与安装文件已在本次本地检查中逐字对应，但这不是持续的供应链认证。

文件另含冻结时钟的合成反例：在默认 10 ms 采样门下，输入从 1 变为 0.5，两次输出仍可为 -2；这模拟程序循环未跨过采样门，并非真实机器耗时测量。接入检查同时核查真实到达间隔的 P/I/D、丢包不调用、旧观测、全新状态与 P-only 对照，命令为：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s integration_tests -v
```

这是一份执行真实公开库的教学接入案例，不是 PID 调参、论文复现、硬件效果、稳定性证明或独立人类采用。案例中的三种策略仍共享发送上限，不保证实际发送量相同。

## English

From the source root, create a virtual environment, install the hash-locked optional requirement and run `python -m examples.simple_pid_case --out runs/pid-first`. Use that environment's interpreter for every command. The standard-library core does not require simple-pid. The source command checks the output before configuration reads or computation. If the output exists or a parent is a file, keep it and retry the original configuration and gains in a fresh directory. This early check does not guarantee later storage availability.

The adapter uses delivered position measurements, a simulation arrival clock and explicit arrival gaps. The first observation initializes P only; later I/D updates use received-observation gaps. A fresh PID is created for each policy. `controller.json` records provenance, actual gains and every component update. The frozen-clock case is a synthetic negative control, not a timing benchmark. Internal PID clipping and downstream actuator clipping have separate scopes. This is a pinned integration recipe, not tuning, stability or adoption evidence.
