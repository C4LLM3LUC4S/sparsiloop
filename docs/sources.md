# 公开来源与路线

查阅日期：2026-10-22。下列材料提供研究背景，不表示本原型已经运行其代码或复现其结果。

- [Tabuada, 2007, Event-Triggered Real-Time Scheduling of Stabilizing Control Tasks](https://ieeexplore.ieee.org/document/4303247/)，DOI 10.1109/TAC.2007.904277；作者[公开稿](https://www.seas.ucla.edu/~tabuada/Papers/EventTriggered.pdf)。用于确认按测量误差与状态量触发更新的研究背景。本原型的两个教学规则自行定义，不移用文中的稳定性条件。
- [Yang 等，ICML 2025，Neural Event-Triggered Control with Optimal Scheduling](https://proceedings.mlr.press/v267/yang25av.html)。已核出版社摘要与书目信息；全文公式和官方训练实现尚未复现。其神经控制器及理论保证不属于本轮交付。
- [safe-control-gym 官方仓库](https://github.com/learnsyslab/safe-control-gym)：已有控制/RL环境、约束、扰动和控制器实现，后续适配候选；本轮不宣称兼容或复现它。
- [ControlBench 官方仓库](https://github.com/maximilian467/ControlBench)：已有控制器比较框架，后续需与其实际协议对照；本轮没有完成全面能力差异评估。

当前定位是一个待验证的产品假设：让消息开销、控制器可见信息和失败边界可检查，提供容易上手的本地实验。不声称首创事件触发平台或优于上述项目。

第一阶段之外的待办：公开控制器接入案例；相同实际消息数的配对比较/预算扫描；采样网格敏感性；多种子汇总；有延迟抖动时的乱序与旧包政策；双向链路；准确的计算耗时测量；独立用户操作。这些尚未完成，不混入当前演示结果。
