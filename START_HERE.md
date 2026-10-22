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

先读报告里的“如何读这份结果”。MFAC 是在线估计，ILC 跨轮次学习，RL 要看冻结后的未训练种子评测；三个案例的条件不同，不能直接排榜。完整公式、导出和限制见 [经典控制案例](docs/classic-controllers.md)。

With Python 3.10+, extract the full repository and run `python quickstart.py`. It binds an available loopback port before opening your browser. No installation, account or additional dependency is required. Keep the terminal open; Ctrl+C stops the server. For static learning reports, run `python quickstart.py --mode controllers`; `--no-open` disables browser opening. Each report uses a fresh directory. These are explicit source-preview paths, not an installed-wheel claim; regular installation is `python -m pip install .`.
