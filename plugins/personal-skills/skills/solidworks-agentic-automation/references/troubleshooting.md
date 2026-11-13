# 常见问题排查

## 连接问题

### 无法连接到 SolidWorks

```
错误: pywintypes.com_error: (-2147221005, '无效的类字符串', None, None)
```

**原因**: SolidWorks 未安装或 COM 未注册
**解决**: 确认 SolidWorks 已安装，尝试指定版本号连接：
```python
sw = win32com.client.Dispatch("SldWorks.Application.32")  # SW 2024
```

### GetActiveObject 失败

```
错误: pywintypes.com_error: (-2147221021, '操作不可用', None, None)
```

**原因**: SolidWorks 未运行
**解决**: 先手动启动 SolidWorks，或使用 `Dispatch` 启动新实例

### Python 32/64 位不匹配

**原因**: Python 位数必须与 SolidWorks 一致（通常为 64 位）
**解决**: 安装 64 位 Python

## 类型错误

### SelectByID2 类型不匹配

```
错误: TypeError: Objects of type 'NoneType' can not be converted to a COM VARIANT
```

**解决**: 对 Callout 参数使用显式 VARIANT：
```python
from win32com.client import VARIANT
import pythoncom
callout = VARIANT(pythoncom.VT_DISPATCH, None)
model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, callout, 0)
```

### by-ref 参数错误

**解决**: 使用 VARIANT 包装输出参数：
```python
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
```

## 操作失败

### 特征创建失败（返回 None）

常见原因：
1. **未选择正确实体** - 检查 SelectByID2 的实体名称和类型
2. **草图未完全约束** - 添加足够的约束和尺寸
3. **草图有开环** - 拉伸需要闭合轮廓
4. **单位错误** - API 使用米，不是毫米

### 基准面选择失败

**原因**: 中英文名称不同
**解决**:
```python
# 尝试英文名称
success = model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, None, 0)
if not success:
    # 尝试中文名称
    model.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, None, 0)
```

### 保存/导出失败

检查错误码：
```python
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
success = model.Extension.SaveAs(path, 0, 1, None, errors, warnings)
print(f"错误码: {errors.value}, 警告码: {warnings.value}")
# 查看 references/export.md 中的错误码对照表
```

## 未封装 API 调用

当需要使用本 skill 尚未封装的 SolidWorks API 时：

1. 先查 SolidWorks 官方 API 文档或本地 SDK 文档，确认接口签名和枚举。
2. 用最小脚本验证接口，不要直接嵌入大任务。
3. 对 COM 返回值做 `None` / `False` 检查，并打印错误码/警告码。
4. 完成后把稳定写法补进 `scripts/`，把坑位补进本文件或对应 `references/*.md`。

沉淀模板：

```text
### <API 或错误现象>

场景:
错误/症状:
原因:
稳定写法:
  # 最小可运行示例
验证方式:
```

## 历史特征树与参数 DOE

### 不要直接修改继承圆周阵列的实例数

场景: 在已有零件上优化局部重复结构，同时保留接口、孔系和下游特征。

症状: 直接改变历史圆周阵列实例数可能触发下游特征错误，或重建为意外的多个实体。
文件仍可能导出 STEP，但几何已不再与母模型可比。

处理:

1. 将圆周阵列实例数视为特征树拓扑身份，不作为普通连续 DOE 参数。
2. 若必须改变支路数，从已验证母模型重建中间支路及依赖它的下游特征，不要原位改阵列计数。
3. 每个候选都检查特征错误、抑制状态、实体数、外包络、接口尺寸、STEP 时间戳和预览图。
4. 预期单体的结构若 `body_count != 1`，在修复前禁止送入单体求解流程。

### 未确认草图语义时保留尺寸身份

对于历史模型中的 `D2@草图2`、`D6@草图2` 等尺寸，先把完整参数名和值作为
权威身份记录。未在 SolidWorks 草图尺寸界面人工确认前，不要自行把它们重命名或
解释为“实体宽度”“开口宽度”“框长”等几何语义。DOE、报告和 YAML 必须保留原始
参数名；人工确认后再另加 `semantic_label`，不要覆盖原始身份。

### pywin32 写入外观数组后零件意外透明

症状: 使用普通 Python `list` 或 `tuple` 写入 `MaterialPropertyValues` 后，模型颜色错误、
装配预览半透明。读回九个数值时可见 RGB 与透明度错位，例如透明度被意外写成约 `0.82`。

原因: 当前 SolidWorks/pywin32 组合没有把普通序列稳定封送为 COM `double[]`。

稳定写法:

```python
values = [r, g, b, ambient, diffuse, specular, shininess, transparency, emission]
variant = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values)
target.MaterialPropertyValues = variant
```

写入后立即读回 `list(target.MaterialPropertyValues)`，逐项核对九个值。保存预览前调用
`model.ViewDisplayShaded()` 并清空选择；参考轴需要选中后调用 `model.BlankRefGeom()`。

## 性能优化

### 动态 COM 无法枚举特征树

症状: `FirstFeature`、`IFirstFeature` 或 `FeatureManager.GetFeatures(True)` 在部分
SolidWorks/pywin32 动态分派组合中返回“找不到成员”或“无法读只写属性”，但建模、重建、
保存、STEP 导出和预览仍正常。

处理:

1. 不要伪造空特征树或把枚举失败报告为零个特征；保留 `feature_error` 和 `warn` 状态。
2. 继续执行独立的返回值、重建、实体数、输出文件和预览检查。
3. 若特征级审计是硬性要求，为目标 SolidWorks 版本生成匹配的 COM 类型库包装，或使用
   官方 API 支持的 VBA/.NET 探针做最小验证，再接入生产流程。
4. 将特征摘要视为一个可选证据通道，不能让它成为所有 CAD 交付的唯一成功依据。


### 大型装配体操作慢

```python
# 开启后台处理模式
model.FeatureManager.EnableFeatureTree = False
model.ActiveView.EnableGraphicsUpdate = False

# ... 执行操作 ...

# 恢复并刷新
model.FeatureManager.EnableFeatureTree = True
model.ActiveView.EnableGraphicsUpdate = True
model.GraphicsRedraw2()
```

### 批量操作优化

```python
# 禁用自动重建
sw.UserControl = False

# 执行批量操作...

# 手动重建
model.EditRebuild3()
sw.UserControl = True
```

## 版本号对照

| SolidWorks | 修订号 | ProgID |
|---|---|---|
| 2020 | 28 | SldWorks.Application.28 |
| 2021 | 29 | SldWorks.Application.29 |
| 2022 | 30 | SldWorks.Application.30 |
| 2023 | 31 | SldWorks.Application.31 |
| 2024 | 32 | SldWorks.Application.32 |
| 2025 | 33 | SldWorks.Application.33 |

公式: `修订号 = (年份 - 2000) + 8`
