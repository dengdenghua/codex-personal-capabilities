# 装配体 API 参考

## 添加组件

`IAssemblyDoc.AddComponent4` 需要目标零件已加载到当前 SolidWorks 会话。批量脚本可先
静默打开零件，完成组件插入后再关闭独立零件窗口；若接口返回 `None`，先检查加载状态、
文件路径和活动文档类型，不要立即重复启动 SolidWorks。

```python
component = asm_model.AddComponent4(
    CompPath,    # str: 零件/子装配体文件路径
    ConfigName,  # str: 配置名（空字符串=默认）
    X, Y, Z      # float: 组件包围盒中心的初始位置（米），不是零件原点
)
```

`AddComponent4` 只提供初始姿态。工程装配必须继续创建真实配合，并从
`Component2.Transform2`、端面间隙和同轴偏移反向验收最终姿态。不能把
`AddComponent4` 的坐标摆放或把所有组件固定当成完成装配。

## 配合类型

### AddMate5 参数

```python
mate = asm_model.AddMate5(
    MateTypeFromEnum,   # int: 配合类型（见下表）
    AlignFromEnum,      # int: 对齐方式（0=Aligned, 1=Anti-Aligned）
    Flip,               # bool: 翻转方向
    Distance,           # float: 距离值（距离配合时使用）
    DistanceAbsUpperLimit,  # float: 距离上限
    DistanceAbsLowerLimit,  # float: 距离下限
    GearRatioNumerator,    # float: 齿轮比分子
    GearRatioDenominator,  # float: 齿轮比分母
    Angle,                 # float: 角度（弧度）
    AngleAbsUpperLimit,    # float: 角度上限
    AngleAbsLowerLimit,    # float: 角度下限
    ForPositioningOnly,    # bool: 仅用于定位
    LockRotation,          # bool: 同心配合时是否锁定转动
    WidthMateOption,       # int: 宽度配合选项；普通配合传 0
    ErrorStatus            # ByRef int: swAddMateError_e 输出错误码
)
```

Python COM 中 `ErrorStatus` 必须使用 by-ref `VT_I4`：

```python
error_status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
mate = asm_model.AddMate5(
    mate_type, alignment, False,
    0.0, 0.0, 0.0, 0.0, 0.0,
    0.0, 0.0, 0.0,
    False, lock_rotation, 0, error_status,
)
assert mate is not None
assert int(error_status.value) == 1  # swAddMateError_NoError
```

当前接口是 15 个参数。旧的 12 参数示例会在本机动态 COM 中报参数数量错误。

### 对齐方式枚举

| 值 | 名称 | 说明 |
|---|---|---|
| 0 | swMateAlignALIGNED | 对齐 |
| 1 | swMateAlignANTI_ALIGNED | 反向对齐 |
| 2 | swMateAlignCLOSEST | 选择最近可解姿态，自动装配优先使用 |

### 配合类型枚举

| 值 | 名称 | 说明 |
|---|---|---|
| 0 | swMateCOINCIDENT | 重合 |
| 1 | swMateCONCENTRIC | 同心 |
| 2 | swMatePERPENDICULAR | 垂直 |
| 3 | swMatePARALLEL | 平行 |
| 4 | swMateTANGENT | 相切 |
| 5 | swMateDISTANCE | 距离 |
| 6 | swMateANGLE | 角度 |
| 8 | swMateLOCK | 锁定 |
| 20 | swMateWIDTH | 宽度 |

## 组件操作

```python
# 获取所有组件
components = asm.GetComponents(True)  # True=仅顶层

# 遍历组件
for comp in components:
    print(comp.Name2)           # 组件名
    print(comp.GetPathName())   # 文件路径
    print(comp.IsSuppressed())  # 是否被压缩

# 压缩/解压缩
comp.SetSuppression2(3)  # swComponentResolved

# 替换组件
asm.ReplaceComponents2(newPath, configName, False, replaceType, True)
```

`swComponentSuppressionState_e` 的实际值是：`0=Fully suppressed`、
`1=Lightweight`、`3=Resolved`。因此 `SetSuppression2(0)` 会把组件完全压缩，
不能用作“解析/解压缩”。

## 干涉检查

```python
interference = asm.InterferenceDetection
interference.TreatSubAssembliesAsComponents = False
interference.TreatCoincidenceAsInterference = False
interference.Done()
count = interference.GetInterferenceCount()
```

## 爆炸视图

```python
# 创建爆炸视图需要通过配置管理器
config = model.GetActiveConfiguration()
# 使用 IExplosionStepData 创建爆炸步骤
```

## 大型装配体生成建议

- 超过 20 个零件时，优先分批生成零件，保存后关闭文档，避免 SolidWorks COM 进程长时间堆积打开文档。
- 装配前先确认所有零件文件真实存在，必要时先重启 SolidWorks 再执行装配步骤。
- `AddComponent4` 在某些状态下要求零件已被打开或当前装配体为活动文档；失败时先 `open_document(sw, part_path, silent=True)` 再添加。
- 装配脚本应记录失败组件清单，不要在缺件情况下声称装配完整。
- 生成后必须用 `sw_review.py` 导出多视角预览图；如果预览图变成黑块、空白或只显示局部组件，应视为装配不合格并回退到更小批次。

## 真实装配的最小验收闭环

1. 选择一个刚性主件固定为装配基准，其余主件不得靠 `FixComponent` 冒充配合。
2. 回转接口通常使用一组同心配合加一组端面重合配合；需要消除周向自由度时，在同心配合中启用 `LockRotation`。
3. 优先根据圆柱半径、轴向、平面法向、平面位置和面积筛选实际 `Face2`，再用 `Select4` 配合，避免依赖本地化或会变化的面名称。
4. 每个配合检查：两个实体均选中、选择计数为 2、`Mate2` 非空、`ErrorStatus=1`。
5. 重建后读取组件变换和包围盒，验证端面间隙、同轴偏移、轴向叠层长度和旋转矩阵。项目未另行定义时，数值公差建议从 `0.01 mm` 起。
6. 主件应达到完全约束状态；然后执行主件干涉检查，并把重合接触面排除在干涉之外。
7. 最后导出等轴测、轴向侧视和两个端视图。截图只作为视觉复核，数值验收和真实 mate 才是主证据。

## 官方 API 依据

- [IAssemblyDoc::AddMate5](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAssemblyDoc~AddMate5.html)
- [IAssemblyDoc::AddComponent4](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAssemblyDoc~AddComponent4.html)
- [swComponentSuppressionState_e](https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swComponentSuppressionState_e.html)
- [swMateAlign_e](https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swMateAlign_e.html)
