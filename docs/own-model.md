# 接入自己的模型 / Bring your own model

如果你已经有一个模型，想知道减少传感器消息后还能不能完成控制任务，可以从这里开始。先用熟悉的输入检查模型算得是否正确，再比较误差、发送次数和运行失败的位置。当前支持一个控制输入，状态可以是一维，或由位置和速度两部分组成。

## 完整路径

Python 3.10+，完整解压源码并进入项目目录，无需第三方依赖：

```sh
python -m examples.own_model_case --out runs/own-model
```

打开 `runs/own-model/report.html`，先看‘少发一些消息，会发生什么？’。这个例子让一个偏离目标位置的执行器回到原位，位置为 0 就表示到达目标。它使用简化数学模型，参数没有经过真实设备校准。公式为 `dx/dt=-0.4*x+1.2*u`；每段时间内保持输入不变，并直接用解析解计算。

报告之外，目录中还保留了这些文件：

- `model.json`：参数、单位、来源与案例源码 SHA-256。
- `network/result.json` 与轨迹 CSV：三种策略，共同发送上限，实际发送数分别保留。
- `traffic/study.json` 与 CSV：两个阈值、两个种子、两个事件策略，共八个事后实际发送量配对。
- `controllers/report.html`、JSON、CSV、冻结策略：同一模型上的 MFAC/ILC/RL 各自适用流程，全部训练与试次保留。

`--decay 0.7 --gain 1.0` 显式改变模型参数；更换 `--out` 目录保留前次结果。成功导出不等于所有仿真完整完成，要检查每条状态和覆盖。

## 最小接口

```python
import math
from event_control_lab import Config, PlantAdapter, compare

def factory(config):
    def step(state, held_input, dt):
        decay, gain = 0.4, 1.2
        response = -math.expm1(-decay * dt)
        return (state[0] * math.exp(-decay * dt) + gain * held_input * response / decay,)
    return step

model = PlantAdapter(
    name="My actuator", state_layout="scalar", factory=factory,
    parameters={"decay_per_second": 0.4, "input_gain_per_second": 1.2},
    state_units=("normalized_displacement",), input_unit="normalized_command",
    source="My retained implementation and parameter record")
result = compare(Config(), plant=model)
```

方程和声明参数应相符；保存自己的源码、权重、版本和标定依据。`source_sha256` 可记录文件摘要。工具保留声明和适配器核心指纹，不自动检查声明与代码相符、不自动打包私人源码。

`compare(config, controller_factory=..., plant=model)` 同时接自己的控制器；`study(spec, controller_factory=..., plant=model)` 和 `controller_lab(spec, method="ilc", plant=model)` 复用同一模型。控制器仍只收到 `Observation(values, sample_time, arrival_time)`；模型收到真状态、限幅控制加该步扰动以及 `dt`。这是本地调用约定，并非恶意代码沙箱；网页不接收模型代码。

想在同一对象上先选发送门槛，再换一组条件复核？见[本地模型选择流程](planned-models.md)。它要求模型的 `source_sha256`，保存完整声明，下一次必须显式传入匹配模型；原有接口中可选的来源记录，不因此变成自动认证。

## 布局、时间和重置

- `scalar` 是一维输出；`double_integrator` 在适配器中选择**位置、速度**布局，不表示采用内置双积分方程。`Config.plant` 必须匹配布局；实际动力学以 `plant.kind=local_python_adapter` 和声明为准。
- 单输入、零目标，初态取 `initial_position` 和可选 `initial_velocity`。多输入、任意状态基、观测映射、非零参考轨迹暂未支持。RMSE 按第一状态计算；二次代价是协议固定权重的指标，不是能耗，不跨单位或尺度比较。
- 每个策略、ILC试次、训练轮次、评测运行均调用 `factory(config)`。工厂应重置内部记忆和随机流，不要复用有记忆的全局单例。`step` 的状态输入为不可变 tuple，返回下个状态向量。
- 模型可按已完成步数累计时间。额外随机过程需保存种子规则和参数；核心随机输入相同不证明模型内部随机性已对齐。
- 事后周期参考只改变通信预算，模型和控制器用同一事件配置初始化；导出两种配置，避免参考预算暗中改变对象。
- 每区间推进一次，末端 `T` 不再调用控制器。自己的积分误差另行核查；内置 `grid-check` 的解析积分只支持内置对象，不能验证自定义模型。
- MFAC、ILC 仍要求完整规则采样和无延迟/丢包/噪声训练；RL 保持训练/评测分离。接口不赋予方法尚未实现的条件支持或收敛保证。

## 失败与恢复

| 记录 | 下一步 | 复核 |
| --- | --- | --- |
| 初始化/更新异常、维数或数值错误 | 读 JSON `error`，核工厂、返回向量、积分器和单位 | `plant_error` 保留前缀，完整时域指标为 `null`；先核已知输入参考，再用新目录重跑 |
| 有限状态超过 `state_limit` | 核方程、输入尺度、初态和反馈符号；有依据才重定范围 | 原超限状态和失败保留，不用缩短时域或丢弃失败美化均值 |
| 预算阻止请求、到达数低 | 看账本和发生时刻，再明确调整预算、阈值或网络条件 | 比较实际尝试、到达与完整时域；共同上限不是相同成本 |

返回值接受可转为 binary64 的实数（不含布尔）。各分量须有限、绝对值不超过 `1e100`，防止积分平方溢出；这与更小的仿真状态上限不同。初始化失败无采样；更新失败保留已发生的采样通信和上一个有效状态，失败区间不计完成时域。

Acceptance: verify an independent known-input trajectory, reset each run, preserve units/source/parameters and failures, then inspect packet accounting and eligible comparisons. This is an engineering example; independent adoption and human benefit remain to be measured.
