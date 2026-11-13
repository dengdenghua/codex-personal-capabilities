# 水循环智能睡眠产品：设计检查入口



阶段评审与综合评审请先用 [智能睡眠产品结构评审总入口](../../sleep-structural-review/SKILL.md)，按概念、详细设计、EVT、DVT、PVT及变更阶段选择专项，并使用统一问题、风险和试验待办模板。本页保留专项速查。



当前产品架构：类似Eight Sleep的床边温控主机＋循环液体＋柔性水垫＋传感/控制。此为用户确认的产品方向；制冷方式、液体配方、电源、开闭式回路、额定参数、用户范围和市场未确认时保持待定，不把竞品参数或光学设备背景带入。



## 优先专项



| Skill | 范围 | 项目 | 重点资源 |

|---|---|---|---|

| [sleep-hydraulic-leak-review](../../sleep-hydraulic-leak-review/SKILL.md) | 水路、密封、压力包络与泄漏联动 | HY01–HY20 | 清单＋五阶段验证计划 |

| [sleep-flexible-waterpad-review](../../sleep-flexible-waterpad-review/SKILL.md) | 水垫流道、焊缝、局部压载与复合寿命 | WP01–WP20 | 清单＋五阶段验证计划 |

| [sleep-temperature-fault-review](../../sleep-temperature-fault-review/SKILL.md) | 床面温控、双区串扰与故障保护 | TC01–TC20 | 清单＋五阶段验证计划 |

| [sleep-condensation-review](../../sleep-condensation-review/SKILL.md) | 局部露点、冷桥、隔汽与凝露传播 | CD01–CD20 | 清单＋五阶段验证计划 |



## 其他专项



| Skill | 范围 | 项目 |

|---|---|---|

| [sleep-acoustic-vibration-review](../../sleep-acoustic-vibration-review/SKILL.md) | 泵/风扇/气泡与夜间结构传振 | NV01–NV12 |

| [sleep-fluid-hygiene-review](../../sleep-fluid-hygiene-review/SKILL.md) | 液体材料相容、腐蚀、堵塞与清洗卫生 | FH01–FH12 |

| [sleep-fill-prime-service-review](../../sleep-fill-prime-service-review/SKILL.md) | 灌注、排气、补液、快接与停用重启 | FS01–FS12 |

| [sleep-contact-sensing-review](../../sleep-contact-sensing-review/SKILL.md) | 床面硬点、舒适、传感固定与信号性能 | CS01–CS12 |



## 既有skill的睡眠专项补充



- [散热与风道](../../mechanical-thermal-airflow-review/SKILL.md)：新增[THS01–THS12](../../mechanical-thermal-airflow-review/references/sleep-system.md)，按冷端吸热＋制冷输入核热端排热，明确辅助热边界和双区工况。

- [内部堆叠安规](../../internal-stack-safety/SKILL.md)：新增[SAS01–SAS14](../../internal-stack-safety/references/sleep-system.md)，先核产品分类，再查漏液、潮湿、人体长期接触及故障安全。旧AV/ICT条款不默认适用。

- [通用结构五套](structural-review-index.md)继续用于几何、公差、装配、热和制造基础审查；按问题加载，不必每次全部展开。



## 联合评审规则



先HY压力/液体边界与WP载荷/水道，再TC温控故障和CD露点/湿害；相互引用测点和证据编号，避免重复计热或把一个试验替代其他失效机理。专项缺失输入不阻止其他独立预审；没有证据的项保留待确认。



依据分S?候选标准、S已核适用条文、E工程经验；V验证方式单独列。标准来源主要是官方范围/目录，不冒充已核正文。所有压力、载荷、温度、循环数、样本量及寿命宣称由批准规格/风险评估决定。



本索引只组织设计检查，不代表任何试验已完成、产品获证或医疗效果获验证。故障/极限试验使用台架和模拟负荷，不让睡眠中的用户承担验证风险。
