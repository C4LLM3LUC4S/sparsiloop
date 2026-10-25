# SparsiLoop · 事件触发控制实验室

**少发一些传感器消息，会让控制效果变差多少？**

SparsiLoop 帮你在电脑上试一试：调整发送次数、延迟和丢包，比较定期发送与按变化发送时的控制误差。你可以查看消息是否到达、误差在哪里变大，再带走完整数据继续分析。适合控制与机器人课程中的实验，也可作为接入自己模型的起点。

A local lab to compare event-triggered and periodic control under communication budgets, delay and packet loss. Inspect each message and export reproducible results.

[English guide](README.en.md) · [第一次使用](START_HERE.md) · [名称与简介](BRANDING.md)

**当前是 `0.1.0a7` alpha 发行版。** 源码包里的 PID 示例也会先检查保存路径，再读取配置或开始计算。路径被占用时，保留原文件，把输出换到新目录，沿用原配置和增益重试。自有模型示例的提前检查、报告指引与本地恢复继续可用。 目前提供两个归一化教学对象、一条传感器上行链路、三种发送策略及独立的学习控制案例。网页与命令行共用 Python 仿真核心，控制器只能读取已经到达的测量。Python 3.10+；核心和本地服务不需要第三方依赖、账户、API 密钥或 GPU。


**[下载完整离线包 / Complete offline bundle](https://github.com/C4LLM3LUC4S/sparsiloop/releases/download/v0.1.0a7/SparsiLoop-0.1.0a7.zip)** · [发行说明与校验 / Release and checksums](https://github.com/C4LLM3LUC4S/sparsiloop/releases/tag/v0.1.0a7) · [旧文件与源码恢复 / Saved-file recovery](docs/source-recovery.md)

## 从你要做的事开始

先固定一个要回答的问题，再选实验路径。如何判断这次有没有帮上忙、多标签页忙碌时怎么办，见[实际用途、运行规模与恢复](docs/reliability.md)。

| 想做什么 | 从哪里开始 |
| --- | --- |
| 先看看少发消息有什么影响 | 运行 `python quickstart.py`，在网页调整条件后比较误差与实际消息数 |
| 在消息上限内选一个发送门槛，再换条件复核 | [选择与复核](docs/planned-study.md)：网页或本地命令保存全部候选与失败，测试结果不会改选 |
| 用训练好的 Q 策略选发送方式 | [冻结策略复用](docs/planned-policy.md)：网页可复用前一结果，也可载入完整文件；不重新训练 |
| 在单独评测与下一轮计划之间接着走 | [完整历史接续](docs/policy-history.md)：网页或本地 API/CLI 保留起点与后续阶段，不用手抄已用编号 |
| 换成自己的对象模型 | [本地模型接入](docs/planned-models.md)：显式保留参数、单位和来源；网页不上传或执行模型代码 |
| 换电脑复核，或只重绘旧报告 | [环境记录与重绘](docs/planned-study.md#换一台电脑时先看环境记录)：缺失的旧环境仍未知，不再运行的步骤不会冒充新测试 |

SparsiLoop 是公开项目名称，Python 模块名仍为 `event_control_lab`。下面从最短的本地使用路径开始。

## 本地打开

最短入口：完整解压后运行 `python quickstart.py`，自动选择空闲本地端口并打开网页。看三种学习控制案例用 `python quickstart.py --mode controllers`。无需安装或激活环境；详见 [第一次使用](START_HERE.md)。下文保留原有模块命令。

首次使用：下载本仓库的 Code → Download ZIP 并解压，或克隆 `https://github.com/C4LLM3LUC4S/sparsiloop.git`。进入解压后的项目文件夹。无需购买服务或配置密钥。

在本项目文件夹中运行：

```powershell
python -m event_control_lab serve --port 8788
```

浏览器打开终端显示的 `http://127.0.0.1:8788`。调整发送上限、延迟或丢包概率后点击“运行比较”。先比较同一位置偏差指标，再核对实际发送量；相同上限不代表相同实际通信量。预算为零或延迟很长时也可以运行，用于观察失去反馈后的情况。

服务仅绑定本机回环地址。关闭运行它的终端或按 Ctrl+C 停止；没有云部署。

## 经典控制与学习案例

在网页点击“试试 MFAC、ILC 和强化学习”，就能选择方法、调整参数、运行并下载完整离线报告。也能选择保存的策略，用新种子继续测试；见[网页实验说明](docs/web-recipes.md)。需要更多参数或更大规模时，使用下面的命令。

```powershell
python -m event_control_lab controller-lab --out runs/controllers
```

打开新目录中的 `report.html`。MFAC 在运行时估计模型对输入的响应；ILC 反复执行同一个任务，用上一轮误差调整下一轮输入；强化学习先训练策略，再固定策略到新的随机种子上测试。每轮数据和失败均保留；RL 同时给出未训练和固定反馈参考，不保证优于它们。三者首版均使用一阶教学对象，MFAC/ILC 要求完整规则采样；它们还不是通用的事件触发版本。可用 `--method mfac`、`ilc`、`rl` 单独运行，完整参数、公式与限制见 [经典控制案例](docs/classic-controllers.md)。

## 保存可重复结果

强化学习训练后的策略可以[重新加载后单独测试](docs/saved-policy.md)，不需要重跑训练。新入口会核对训练时的时间步长、时域和输入上限，在新种子下输出独立报告；目前支持内置一阶模型。

```powershell
python -m event_control_lab compare --config examples/default.json --out runs/first
python -m unittest discover -s tests -v
```

输出 `result.json` 和 `trajectory.csv`，已有目录拒绝覆盖。网页也可下载相同结构的 JSON 和 CSV。JSON 包含参数、Python 版本、核心源码指纹、每步外部随机输入、消息账本和轨迹。对内置控制器，同一源码和 Python 环境中，同一配置的完整结果应逐字可重复；跨平台浮点逐位一致尚未建立。

## 接自己的控制器

已有自己的对象方程？先看[接入自己的模型](docs/own-model.md)。`python -m examples.own_model_case --out runs/own-model` 生成完整导读报告；同一个本地模型接入三种发送策略、事后实际发送量参考及 MFAC/ILC/RL，无需修改核心。当前支持单输入、一维输出或位置—速度布局，参数来源为使用者声明。

```python
from event_control_lab import Config, compare

class MyController:
    def __call__(self, observation):
        return -2.0 * observation.values[0]

result = compare(Config(), controller_factory=lambda config: MyController())
```

每种发送策略都获得一个新控制器实例。接口只传入已到达的测量值、采样时间和到达时间，不传入当前真值。自有控制器的源码、权重和内部随机状态需要另行保存；当前导出不自动打包或认证这些内容。Python 接口并非对恶意代码的信息隔离安全证明；网页不接收或执行上传的 Python 代码。

想接已有库，可以从 [simple-pid 固定版本案例](docs/simple-pid.md) 开始：核查仿真时钟、真实到达间隔、PID 初始化和每次更新的 P/I/D。依赖仅在选择该源码案例时安装，不进入默认核心运行。

## 按实际通信量再比较一次

在网页下方填写几组门槛和随机种子，就能批量比较。程序先记录事件策略的发送次数，再让周期策略按这个次数运行，两次使用相同的外部随机数。失败项保留；参考提前停止导致发送数未对齐时，差值不可用。这是事后描述性对照，不能作为预先调参或普遍优越性的证据。

```powershell
python -m event_control_lab study --spec examples/traffic-study.json --out runs/traffic-check
```

输出 `study.json`、`comparisons.csv`、`trajectories.csv`。完整规则、导出字段和首组固定案例见 [实际通信量对照](docs/traffic-study.md)。

## 换一个步长，结论还一样吗

```powershell
python -m event_control_lab grid-check --spec examples/grid-check.json --out runs/grid-check
```

在无噪声、同一物理延迟与周期发送时刻下，把 20 ms 步长缩为 10 ms、5 ms。导出完整轨迹、不同网格的变化，以及位置 RMSE 相对保持输入解析积分的偏差。事件发送时刻可能随网格改变，工具会保留这些差异，不自动认证收敛。约束、输出解释与错误恢复见 [步长核查](docs/grid-check.md)。

## 解释与范围

- [实验约定](docs/protocol.md)：对象方程、触发规则、时序、预算和指标。
- [产品任务与验收](docs/product-scope.md)：适用用户、实际任务及仍需的收益证据。
- [实际通信量对照](docs/traffic-study.md)：多门槛、多种子、事后周期参考和失败覆盖。
- [步长核查](docs/grid-check.md)：固定物理时间条件，区分触发变化与位置积分偏差。
- [首阶段设计与验收](docs/experiment-plan.md)：本轮问题、固定变量和验证条件。
- [公开来源与后续路线](docs/sources.md)：研究背景与尚未实现的部分。

当前策略是独立编写的教学启发式，NETC 等公开论文算法尚未复现。没有复制私人论文、课程代码或研究参数；不宣称稳定性保证、真实设备效果、AI 算法优越性或实际采用。
