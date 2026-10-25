# SparsiLoop · 事件触发控制实验室

公开项目名称采用 **SparsiLoop**，表示稀疏通信与反馈回路。英文仓库名拟为 `sparsiloop`，与课程复现、RankProbe 各自独立。

## GitHub About

事件触发控制的通信—误差对照实验室。Compare event-triggered and periodic control under packet budgets, delay and loss; inspect every message and export reproducible results.

## 中文简介

面向控制与机器人学习者的本地实验工具：调整通信预算、延迟和丢包，比较事件触发与周期控制，追踪每条消息，并导出可复核的轨迹与指标。

## English introduction

A local lab for students and control researchers to compare event-triggered and periodic feedback under communication budgets, delay and packet loss. Inspect every message, keep failed cases visible and export reproducible trajectories and metrics.

## 展示与交付约定

- 目前是 0.1.0a7 alpha 发行；两个归一化教学对象、三种发送策略，不使用硬件或已训练神经控制器。
- Python 模块仍为 `event_control_lab`，现有命令和导入保持可用；本地分发包名称统一为 `sparsiloop`，新增同名命令入口，旧 `event-control-lab` 命令保留为兼容入口。这些是本地开发包配置，尚未上传 PyPI。
- 自有代码使用 MIT 许可；不带入课程作业、私人论文、参数、原始用户反馈或本地环境。
- 拟用主题：`event-triggered-control`、`networked-control`、`control-systems`、`simulation`、`reproducibility`、`python`。
- 说明依据已实现能力，不把算法普遍优越、稳定性、节时或实际采用写成现有成果。
- 2026-10-22 的精确名称公开检索未找到同名软件；这只是命名选择记录，不作排他性声明。
