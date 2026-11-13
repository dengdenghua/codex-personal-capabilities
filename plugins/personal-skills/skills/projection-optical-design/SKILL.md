---

name: projection-optical-design

description: "续接旧 projection-optical-design 调用，定位保留的个人光学知识档案并转到独立专题 Skill。器件设计直接使用对应专题，跨器件方案使用 projection-system-design。"

---



# 投影光机设计：旧调用兼容入口



原有设计能力已拆为 `projection-optics` 个人插件中的独立 Skill。直接加载当前任务对应的一个或几个专题，无需先经过本入口，不要一次加载全部专题。



| 工作 | 独立 Skill |
| --- | --- |
| 多通道光源、泵浦、合光与时序架构 | projection-source-architecture |
| 收集/准直、像高、焦距与发光面 | collector-lens-design |
| 扩展量、过填充、面角联合接受 | optical-etendue-budget |

| 复眼、单元、阵列与匀光 | flyeye-design |

| TIR/RTIR、合光、空气隙 | projection-prism-design |

| 配色、光谱、亮度和时序 | projection-color-brightness |

| LCOS/PBS偏振、亮暗态与漏光 | lcos-polarization-design |

| 收敛、公差、热态、规范和验收 | optical-design-verification |

| 历史资料、模型与来源定位 | optical-evidence-library |

| 知识图谱、个人记忆与跨会话沉淀 | optical-knowledge-memory |

| 跨器件架构、系统接口和预算 | projection-system-design |



插件安装后的名称可能带 `projection-optics:` 前缀，以当前 Skill 目录为准。若旧会话还未刷新目录，可查已安装插件包中的对应 `skills/<name>/SKILL.md`；不要声称未加载的技能已被执行。




## 私人资料
原目录的 references、assets、scripts 属于私人知识与计算档案，未上传。请在本机单独配置资料库；不要把资料缺失说成已验证。
