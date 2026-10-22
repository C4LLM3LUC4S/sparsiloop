# SparsiLoop · 事件触发控制实验室

**把控制误差与真实通信开销放在一起比较。**

面向控制与机器人学习者的本地实验工具：调整通信预算、延迟和丢包，比较事件触发与周期控制，追踪每条消息，并导出可复核的轨迹与指标。

A local lab to compare event-triggered and periodic control under communication budgets, delay and packet loss. Inspect every message and export reproducible trajectories and metrics.

[English guide](README.en.md) · [名称与简介](BRANDING.md)

**0.0.1，本地开发原型，尚未公开发行。** 目标是让学生、教师和控制研究者直观看见通信次数、信息年龄与控制误差的关系，并能带走完整实验数据。SparsiLoop 是公开项目名称，Python 模块仍为 `event_control_lab`。

目前包括两个归一化教学对象、一条传感器上行链路和三种发送策略。固定反馈控制器只读取已到达的测量；网页与命令行使用同一个 Python 仿真核心。Python 3.10+，核心和网页服务均无需第三方依赖、API 密钥、账户或 GPU。

## 本地打开

在本项目文件夹中运行：

```powershell
python -m event_control_lab serve --port 8788
```

浏览器打开终端显示的 `http://127.0.0.1:8788`。调整发送上限、延迟或丢包概率后点击“运行比较”。先比较同一位置偏差指标，再核对实际发送量；相同上限不代表相同实际通信量。预算为零或延迟很长时也可以运行，用于观察失去反馈后的情况。

服务仅绑定本机回环地址。关闭运行它的终端或按 Ctrl+C 停止；没有云部署。

## 保存可重复结果

```powershell
python -m event_control_lab compare --config examples/default.json --out runs/first
python -m unittest discover -s tests -v
```

输出 `result.json` 和 `trajectory.csv`，已有目录拒绝覆盖。网页也可下载相同结构的 JSON 和 CSV。JSON 包含参数、Python 版本、核心源码指纹、每步外部随机输入、消息账本和轨迹。对内置控制器，同一源码和 Python 环境中，同一配置的完整结果应逐字可重复；跨平台浮点逐位一致尚未建立。

## 接自己的控制器

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

网页下方可扫描多个门槛与种子：先记录事件策略的实际发送数，再生成同一随机输入下、相同尝试发送数的周期参考。失败项保留；参考提前停止导致发送数未对齐时，差值不可用。这是事后描述性对照，不能作为预先调参或普遍优越性的证据。

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
- [实际通信量对照](docs/traffic-study.md)：多门槛、多种子、事后周期参考和失败覆盖。
- [步长核查](docs/grid-check.md)：固定物理时间条件，区分触发变化与位置积分偏差。
- [首阶段设计与验收](docs/experiment-plan.md)：本轮问题、固定变量和验证条件。
- [公开来源与后续路线](docs/sources.md)：研究背景与尚未实现的部分。

当前策略是独立编写的教学启发式，NETC 等公开论文算法尚未复现。没有复制私人论文、课程代码或研究参数；不宣称稳定性保证、真实设备效果、AI 算法优越性或实际采用。
