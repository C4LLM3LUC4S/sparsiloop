# 先做一个能帮助决定的实验

先把问题缩小，例如：“在这份模型、控制器、误差要求和消息上限下，哪组发送门槛值得再测试？”不要先把所有算法跑一遍，再从分数里找一个漂亮结果。

## 先写清四件事

1. **你要做什么决定？** 是选择发送设置，核对步长，还是解释某次失败？一次先回答一个问题。
2. **哪些条件先固定？** 对象与单位、初态、目标、控制器、时钟、网络条件、误差要求，以及选择和预留测试编号。
3. **怎样判定有用？** 结合完整结束情况、完整时段误差和实际消息数判断；相同上限不等于实际通信量相同。
4. **之后怎么复核？** 保存所有候选和失败、原选择、最新历史与源码。复核不改选；看过结果后继续调参，就把这些结果当成开发资料，另定新测试。

MFAC、ILC 和 Q-learning 是不同的教学流程，各有假设，不能因为共用一个网页就按分数排出通用优劣。固定反馈、冻结策略和重新训练也要分开。当前模型不适合你的任务时，就明确记下这个缺口，不靠增加算法名称证明适用性。

## 这是本地实验室，不是多人计算平台

每位使用者在自己的电脑运行。安装者变多，不会把所有实验都挤到同一服务；更先增加的是适配、解释和维护需求。

同一进程的网页六个计算入口共用一个名额：比较、事后对照、经典案例、单独策略评测、选择、复核。占用时，新计算会收到429和稍后重试提示，不排队，也不会因此删除页面保留的旧结果。检查在读取、解析请求正文之前进行。

默认源码启动器和 `serve` 使用有连接上限的本地服务，最多同时处理8个连接，并设读取超时。连接满时会尽力返回503与重试提示；连接过载或客户端提前断开时也可能出现网络错误。健康与静态页面不用计算名额，但仍受连接上限约束。自己把 `Handler` 嵌入其他服务器时，需要另行管理连接数，不能假设已套用默认服务的限制。

这些限制让同机多标签页更可控，不是100用户吞吐、稳定性或公网部署认证。大实验仍可能受单机CPU、内存、响应序列化和下载大小限制，原有时域与容量上限没有放宽。

## 遇到“忙碌”或结果不符合预期

- 先等当前实验结束，再手动重试。连接错误时确认终端仍在运行；重试前核对是否已收到并保存原结果。
- 想扩大规模，优先用本地CLI/API跑声明好的批次，保留失败与完整历史；不要打开更多标签页重复提交同一任务。
- 提问题时写明版本、系统/Python、入口、时长/步长、候选与种子数量，以及预期和实际状态。给一份原创的小JSON就很好，别上传私有模型、真实运行数据或凭据。
- 只有报告生成成功，仍不能认定它对某个真实控制任务有帮助。需要有实际决策、行动及后续复核的记录；开发者压力测试不能替代独立使用证据。

## English

Start with one decision, declared conditions, an acceptance rule and a retained recheck. More algorithms or successful demos do not establish task fit. Each installation computes locally. Within the default local process, all six computation routes share one admission slot before body allocation/JSON parsing; busy requests receive429 rather than entering an unbounded work queue. The default launcher and CLI server cap active connection handlers at8 and use read timeouts; overload may yield503 or a connection error. Health/static reads do not consume the computation slot but remain connection-limited. Custom servers embedding only `Handler` must manage their own connections. These are bounded local recovery measures, not a multi-user cloud service or a throughput guarantee. Keep failed runs, original choices, latest history and exact source; report small shareable reproductions without private data.
