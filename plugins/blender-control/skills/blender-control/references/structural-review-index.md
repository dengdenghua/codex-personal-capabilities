# 结构设计检查清单入口

当前为类似Eight Sleep的水循环智能睡眠产品，系统专项先用 [睡眠产品检查入口](sleep-review-index.md)。本页保留通用五套及安规基础，不再沿用投影设备背景。

按用户要求加载相应skill；单独审查不必把全部清单加载进上下文。综合结构评审可以覆盖全部五套，使用各自ID汇总，避免重复计算或相互矛盾的结论。

| 关注问题 | Skill | 检查项目 |
|---|---|---|
| 装得下、接口对齐、插拔/运动中是否碰撞 | [mechanical-stack-review](../../mechanical-stack-review/SKILL.md) | ST01–ST16 |
| 制造偏差后是否仍配合、缝隙段差是否满足目标 | [mechanical-tolerance-review](../../mechanical-tolerance-review/SKILL.md) | TO01–TO16 |
| 装配顺序、工具、线束及维修路径是否可行 | [mechanical-assembly-service-review](../../mechanical-assembly-service-review/SKILL.md) | AS01–AS16 |
| 导热路径、风道、风扇工作点及温升是否有证据 | [mechanical-thermal-airflow-review](../../mechanical-thermal-airflow-review/SKILL.md) | TH01–TH16 |
| 材料、注塑/钣金/CNC/压铸及表处能否量产 | [mechanical-dfm-review](../../mechanical-dfm-review/SKILL.md) | DF01–DF16 |
| 电气间距、绝缘、固定与接地的安全要求 | [internal-stack-safety](../../internal-stack-safety/SKILL.md) | 既有安规清单，按需补充 |

这五套区分两个维度：

- 依据类别：S?标准候选（待适用性和正文核对）、已核标准要求、E工程经验、批准的项目/供应商文件。标准候选不能直接当法规硬指标。
- 验证方式：几何、计算、文件、实物试装/试验、量产过程数据。标准要求也可能需要实物试验；试验建议并不自动是法规必测。

当前标准资料主要达到官方目录/摘要级，不声称完整条文已核。各skill的basis.md记录日期、版本和读取范围。目标缺失标“待确定”，证据缺失标“待确认”；不能把五套检查全部打勾就宣布整机认证完成。

交叉项分工：ST找问题位置，TO核最差偏差，AS核工序和维修，TH核热/流动，DF核材料工艺。多个检查可引用同一对象或证据编号。涉及安规时另用既有安全skill，不用普通机械间隙代替电气间隙。
