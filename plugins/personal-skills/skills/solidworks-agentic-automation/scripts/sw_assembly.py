"""
SolidWorks 装配体操作工具
"""
try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import get_com_member
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import get_com_member

pythoncom, _win32com, VARIANT = import_com_dependencies()

SW_COMPONENT_SUPPRESSED = 0
SW_COMPONENT_LIGHTWEIGHT = 1
SW_COMPONENT_RESOLVED = 3
SW_COMPONENT_FULLY_CONSTRAINED = 3
SW_MATE_ALIGN_ALIGNED = 0
SW_MATE_ALIGN_ANTI_ALIGNED = 1
SW_MATE_ALIGN_CLOSEST = 2
SW_ADD_MATE_NO_ERROR = 1


def _empty_callout():
    """创建兼容 SelectByID2 的空 Callout 参数。"""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def _byref_i4(value=0):
    """创建适用于 SolidWorks COM 输出参数的 by-ref 32 位整数。"""
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, value)


def _add_mate5(
    asm_model,
    mate_type,
    alignment=SW_MATE_ALIGN_CLOSEST,
    flip=False,
    distance=0.0,
    distance_upper=0.0,
    distance_lower=0.0,
    gear_numerator=0.0,
    gear_denominator=0.0,
    angle=0.0,
    angle_upper=0.0,
    angle_lower=0.0,
    positioning_only=False,
    lock_rotation=False,
    width_mate_option=0,
):
    """调用当前 AddMate5 的完整 15 参数签名并校验错误码。"""
    error_status = _byref_i4(0)
    mate = asm_model.AddMate5(
        mate_type,
        alignment,
        flip,
        distance,
        distance_upper,
        distance_lower,
        gear_numerator,
        gear_denominator,
        angle,
        angle_upper,
        angle_lower,
        positioning_only,
        lock_rotation,
        width_mate_option,
        error_status,
    )
    if mate is None or int(error_status.value) != SW_ADD_MATE_NO_ERROR:
        raise RuntimeError(
            f"AddMate5 failed: mate_type={mate_type}, "
            f"alignment={alignment}, error_status={int(error_status.value)}"
        )
    return mate


def _select_by_id(extension, entity_name, entity_type, append=False, mark=0):
    """
    统一封装 SelectByID2，避免 None 在部分 SolidWorks 版本中触发类型不匹配。

    参数:
        extension: ModelDocExtension 对象
        entity_name: 实体名称
        entity_type: 实体类型字符串
        append: 是否追加选择
        mark: 选择标记

    返回:
        bool
    """
    return extension.SelectByID2(
        entity_name, entity_type, 0, 0, 0, append, mark, _empty_callout(), 0
    )


def _require_named_pair(asm_model, entity1_name, entity1_type, entity2_name, entity2_type):
    """选择一对命名实体，并拒绝静默少选或错选。"""
    asm_model.ClearSelection2(True)
    first = _select_by_id(
        asm_model.Extension, entity1_name, entity1_type, append=False, mark=1
    )
    second = _select_by_id(
        asm_model.Extension, entity2_name, entity2_type, append=True, mark=1
    )
    selected_count = asm_model.SelectionManager.GetSelectedObjectCount2(-1)
    if not first or not second or int(selected_count) != 2:
        asm_model.ClearSelection2(True)
        raise RuntimeError(
            "mate entity selection failed: "
            f"first={bool(first)}, second={bool(second)}, count={selected_count}"
        )


def _select_entity(entity, append, select_data):
    """兼容不同实体类型的 Select4 参数个数。"""
    try:
        return bool(get_com_member(entity, "Select4", append, select_data))
    except TypeError:
        return bool(get_com_member(entity, "Select4", append, select_data, False))


def add_mate_entities(
    asm_model,
    entity1,
    entity2,
    mate_type,
    alignment=SW_MATE_ALIGN_CLOSEST,
    lock_rotation=False,
):
    """直接配合两个 COM 实体，适合按几何特征筛选出的面。"""
    asm_model.ClearSelection2(True)
    manager = get_com_member(asm_model, "SelectionManager")
    data1 = get_com_member(manager, "CreateSelectData")
    data1.Mark = 1
    first = _select_entity(entity1, False, data1)
    data2 = get_com_member(manager, "CreateSelectData")
    data2.Mark = 1
    second = _select_entity(entity2, True, data2)
    selected_count = manager.GetSelectedObjectCount2(-1)
    if not first or not second or int(selected_count) != 2:
        asm_model.ClearSelection2(True)
        raise RuntimeError(
            "mate entity selection failed: "
            f"first={first}, second={second}, count={selected_count}"
        )
    try:
        return _add_mate5(
            asm_model,
            mate_type,
            alignment=alignment,
            lock_rotation=lock_rotation,
        )
    finally:
        asm_model.ClearSelection2(True)


def resolve_component(component):
    """将组件设为完全解析；0 是完全压缩，不能用于解压缩。"""
    return component.SetSuppression2(SW_COMPONENT_RESOLVED)


def is_component_fixed(component):
    """兼容属性/方法两种 COM 暴露形式，判断组件是否固定。"""
    return bool(get_com_member(component, "IsFixed"))


def is_component_fully_constrained(component):
    """Return True when Component2 reports swFullyConstrained."""
    return int(get_com_member(component, "GetConstrainedStatus")) == SW_COMPONENT_FULLY_CONSTRAINED


def fix_component(asm_model, component):
    """选择并固定一个组件，适合作为装配基准件。"""
    asm_model.ClearSelection2(True)
    manager = get_com_member(asm_model, "SelectionManager")
    select_data = get_com_member(manager, "CreateSelectData")
    if not _select_entity(component, False, select_data):
        raise RuntimeError("failed to select component for fixing")
    try:
        get_com_member(asm_model, "FixComponent")
    finally:
        asm_model.ClearSelection2(True)
    if not is_component_fixed(component):
        raise RuntimeError("component remained floating after FixComponent")
    return True


def component_faces(component):
    """Return all available component-context faces, including multibody components."""
    try:
        model = get_com_member(component, "GetModelDoc2")
        part_bodies = list(get_com_member(model, "GetBodies2", 0, False) or [])
    except Exception:
        part_bodies = []

    if part_bodies:
        mapped = []
        part_faces = []
        for body in part_bodies:
            for face in list(get_com_member(body, "GetFaces") or []):
                part_faces.append(face)
                context_face = None
                for method_name in ("GetCorresponding", "GetCorrespondingEntity"):
                    try:
                        context_face = get_com_member(component, method_name, face)
                    except Exception:
                        context_face = None
                    if context_face is not None:
                        break
                if context_face is not None:
                    mapped.append(context_face)
        if mapped:
            return mapped
        if part_faces:
            return part_faces

    try:
        body = get_com_member(component, "GetBody")
        if body is not None:
            return list(get_com_member(body, "GetFaces") or [])
    except Exception:
        pass
    raise RuntimeError("component faces are unavailable in assembly context")


def model_faces(model):
    """Enumerate all faces from every solid body in a loaded part document."""
    faces = []
    for body in list(get_com_member(model, "GetBodies2", 0, False) or []):
        faces.extend(list(get_com_member(body, "GetFaces") or []))
    if not faces:
        raise RuntimeError("loaded part document contains no selectable solid faces")
    return faces


def surface_data(face):
    """Return geometry metadata used to select planar and cylindrical mate faces."""
    surface = get_com_member(face, "GetSurface")
    box = [float(value) for value in get_com_member(face, "GetBox")]
    data = {
        "box_m": box,
        "area_mm2": float(get_com_member(face, "GetArea")) * 1.0e6,
        "type": "other",
    }
    try:
        if bool(get_com_member(surface, "IsPlane")):
            params = [float(value) for value in get_com_member(surface, "PlaneParams")]
            data.update(
                {
                    "type": "plane",
                    "normal": params[:3],
                    "root_mm": [value * 1000.0 for value in params[3:6]],
                }
            )
            return data
    except Exception:
        pass
    try:
        if bool(get_com_member(surface, "IsCylinder")):
            params = [float(value) for value in get_com_member(surface, "CylinderParams")]
            data.update(
                {
                    "type": "cylinder",
                    "origin_mm": [value * 1000.0 for value in params[:3]],
                    "axis": params[3:6],
                    "radius_mm": params[6] * 1000.0,
                }
            )
    except Exception:
        pass
    return data


def add_component(asm_model, part_path, x=0, y=0, z=0, config_name=""):
    """
    向装配体添加零部件

    参数:
        asm_model: IAssemblyDoc (装配体文档)
        part_path: 零件/子装配体文件路径
        x, y, z: 放置位置（米）
        config_name: 配置名称，空字符串使用默认配置

    返回:
        IComponent2 对象
    """
    component = asm_model.AddComponent4(part_path, config_name, x, y, z)
    if component:
        resolve_component(component)
        print(f"已添加组件: {part_path}")
    else:
        print(f"添加组件失败: {part_path}")
    return component


def add_mate_coincident(
    asm_model,
    entity1_name,
    entity1_type,
    entity2_name,
    entity2_type,
    alignment=SW_MATE_ALIGN_CLOSEST,
):
    """
    添加重合配合

    参数:
        entity1_name/entity2_name: 实体名称（面、边、点等）
        entity1_type/entity2_type: 实体类型字符串（"FACE", "PLANE", "EDGE", "VERTEX" 等）
    """
    _require_named_pair(
        asm_model, entity1_name, entity1_type, entity2_name, entity2_type
    )
    try:
        return _add_mate5(asm_model, 0, alignment=alignment)
    finally:
        asm_model.ClearSelection2(True)


def add_mate_concentric(
    asm_model,
    face1_name,
    face2_name,
    alignment=SW_MATE_ALIGN_CLOSEST,
    lock_rotation=False,
):
    """添加同心配合"""
    _require_named_pair(asm_model, face1_name, "FACE", face2_name, "FACE")
    try:
        return _add_mate5(
            asm_model,
            1,
            alignment=alignment,
            lock_rotation=lock_rotation,
        )
    finally:
        asm_model.ClearSelection2(True)


def add_mate_distance(asm_model, entity1_name, entity1_type, entity2_name, entity2_type, distance):
    """
    添加距离配合

    参数:
        distance: 配合距离（米）
    """
    _require_named_pair(
        asm_model, entity1_name, entity1_type, entity2_name, entity2_type
    )
    try:
        return _add_mate5(
            asm_model,
            5,
            distance=distance,
            distance_upper=distance,
            distance_lower=distance,
        )
    finally:
        asm_model.ClearSelection2(True)


def add_mate_parallel(asm_model, face1_name, face2_name):
    """添加平行配合"""
    _require_named_pair(asm_model, face1_name, "FACE", face2_name, "FACE")
    try:
        return _add_mate5(asm_model, 3)
    finally:
        asm_model.ClearSelection2(True)


def get_components(asm_model, top_level_only=True):
    """
    获取装配体中的所有组件

    参数:
        top_level_only: True=仅顶层组件, False=包含子装配体中的组件

    返回:
        组件信息列表
    """
    components = asm_model.GetComponents(top_level_only)
    result = []
    if components:
        for comp in components:
            result.append({
                "name": comp.Name2,
                "path": get_com_member(comp, "GetPathName"),
                "suppressed": comp.IsSuppressed(),
                "visible": comp.Visible,
            })
    return result


def suppress_component(asm_model, component_name):
    """压缩（隐藏）组件"""
    _select_by_id(asm_model.Extension, component_name, "COMPONENT")
    asm_model.EditSuppress()


def unsuppress_component(asm_model, component_name):
    """解压缩（显示）组件"""
    _select_by_id(asm_model.Extension, component_name, "COMPONENT")
    asm_model.EditUnsuppress()


def replace_component(asm_model, old_component_name, new_part_path):
    """
    替换装配体中的组件

    参数:
        old_component_name: 旧组件名称
        new_part_path: 新零件文件路径
    """
    _select_by_id(asm_model.Extension, old_component_name, "COMPONENT")
    return asm_model.ReplaceComponents2(new_part_path, "", False, 0, True)


def get_interference_detection(asm_model):
    """运行干涉检查"""
    interference = asm_model.InterferenceDetection
    interference.TreatSubAssembliesAsComponents = False
    interference.TreatCoincidenceAsInterference = False
    interference.Done()

    count = interference.GetInterferenceCount()
    print(f"检测到 {count} 处干涉")
    return count
