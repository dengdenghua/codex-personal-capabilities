"""
SolidWorks 文件导出工具
支持 STEP、STL、IGES、PDF、DXF/DWG、Parasolid 等格式
"""
import os

try:
    from .sw_preflight import import_com_dependencies
    from .sw_connect import create_empty_dispatch_variant, get_com_member
    from .sw_performance import assert_capacity
except ImportError:
    from sw_preflight import import_com_dependencies
    from sw_connect import create_empty_dispatch_variant, get_com_member
    from sw_performance import assert_capacity

pythoncom, _win32com, VARIANT = import_com_dependencies()


def _ensure_parent_dir(file_path):
    """确保输出文件的父目录存在。"""
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def export_to_step(model, output_path):
    """导出为 STEP 格式"""
    return _export_generic(model, output_path)


def export_to_stl(model, output_path, quality="fine"):
    """
    导出为 STL 格式

    参数:
        quality: "coarse" | "fine" | "custom"
    """
    # 设置 STL 质量
    quality_map = {"coarse": 1, "fine": 0}
    if quality in quality_map:
        model.SetUserPreferenceIntegerValue(78, quality_map[quality])  # swSTLQuality
    return _export_generic(model, output_path)


def export_to_iges(model, output_path):
    """导出为 IGES 格式"""
    return _export_generic(model, output_path)


def export_to_parasolid(model, output_path):
    """导出为 Parasolid (.x_t) 格式"""
    return _export_generic(model, output_path)


def export_to_pdf(model, output_path, sheet_names=None):
    """
    导出工程图为 PDF

    参数:
        model: IModelDoc2（必须是工程图文档）
        output_path: PDF 文件路径
        sheet_names: 图纸名称列表，None=所有图纸
    """
    assert_capacity()
    sw = model.GetSldWorksObject()
    pdf_data = sw.GetExportFileData(1)  # swExportPDFData

    if sheet_names is None:
        sheet_names = get_com_member(model, "GetSheetNames")

    if pdf_data:
        pdf_data.SetSheets(0, sheet_names)

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    success = model.Extension.SaveAs(output_path, 0, 1, pdf_data, errors, warnings)

    _print_result("PDF", output_path, success, errors, warnings)
    return success


def export_to_dxf(model, output_path):
    """
    导出为 DXF/DWG 格式
    适用于工程图或钣金展开图
    """
    assert_capacity()
    doc_type = get_com_member(model, "GetType")
    if doc_type == 3:  # 工程图
        return _export_generic(model, output_path)
    else:
        # 零件（钣金展开图）
        return model.ExportToDWG2(
            output_path, get_com_member(model, "GetPathName"),
            1, True, True, False, False, 0, None
        )


def export_flat_pattern_dxf(model, output_path):
    """
    导出钣金展开图为 DXF

    参数:
        model: 钣金零件的 IModelDoc2
    """
    assert_capacity()
    return model.ExportToDWG2(
        output_path, "",
        1,      # 导出展开图
        True,   # 包含外轮廓
        True,   # 包含弯曲线
        False,  # 草图实体
        False,  # 隐藏边线
        0, None
    )


def batch_export(sw, file_paths, output_dir, format_ext=".step"):
    """
    批量导出多个文件

    参数:
        sw: ISldWorks 应用对象
        file_paths: 源文件路径列表
        output_dir: 输出目录
        format_ext: 输出格式扩展名（".step", ".stl", ".igs", ".pdf"）
    """
    import hashlib
    import uuid
    from pathlib import Path
    try:
        from .sw_document_recycler import snapshot_documents, recycle_completed, key
    except ImportError:
        from sw_document_recycler import snapshot_documents, recycle_completed, key
    output_dir = os.path.abspath(os.path.expandvars(os.path.expanduser(output_dir)))
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for file_path in file_paths:
        assert_capacity()
        before = snapshot_documents(sw)
        existing = {key(d['path']) for d in before if d['path']}
        file_path = os.path.abspath(os.path.expandvars(os.path.expanduser(file_path)))
        output_path = os.path.join(output_dir, Path(file_path).stem + format_ext)
        if os.path.exists(output_path):
            raise FileExistsError(output_path)
        model = None
        try:
            model = sw.GetOpenDocumentByName(file_path)
            if model is None:
                doc_type = {'.sldprt':1, '.sldasm':2, '.slddrw':3}[Path(file_path).suffix.lower()]
                errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                model = sw.OpenDoc6(file_path, doc_type, 3, '', errors, warnings)
                if model is None or errors.value:
                    raise RuntimeError(f'Open failed: {file_path}, error {errors.value}')
            activation_error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            active = sw.ActivateDoc3(get_com_member(model, 'GetTitle'), False, 1, activation_error)
            if active is None or activation_error.value not in (0, 2) or key(get_com_member(active, 'GetPathName')) != key(file_path):
                raise RuntimeError('Exact export document activation failed')
            success = export_to_pdf(model, output_path) if format_ext=='.pdf' else _export_generic(model, output_path)
            if not success:
                raise RuntimeError(f'Export failed: {output_path}')
            results.append({'file':file_path, 'success':True, 'output':output_path})
        finally:
            model = None
            owned = []
            for d in snapshot_documents(sw):
                if d['path'] and key(d['path']) not in existing:
                    saved = Path(d['path']).is_file() and not d['dirty']
                    owned.append({'path':d['path'],'completed':saved,
                                  'sha256':hashlib.sha256(Path(d['path']).read_bytes()).hexdigest() if saved else ''})
            cleanup = recycle_completed(sw, {'task_id':'batch-export-'+uuid.uuid4().hex,'documents':owned}, dry_run=False)
            if results and results[-1]['file']==file_path: results[-1]['cleanup']=cleanup
            retained = [d['path'] for d in snapshot_documents(sw) if key(d['path']) in {key(x['path']) for x in owned}]
            if retained:
                raise RuntimeError(f'Batch stopped: preserve unclosed task documents before next case: {retained}')

    success_count = sum(1 for r in results if r["success"])
    print(f"批量导出完成: {success_count}/{len(results)} 成功")
    return results


def _export_generic(model, output_path):
    """通用导出函数（STEP/STL/IGES/Parasolid/DXF）"""
    assert_capacity()
    model.ClearSelection2(True)
    output_path = os.path.abspath(os.path.expandvars(os.path.expanduser(output_path)))
    _ensure_parent_dir(output_path)
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    success = model.Extension.SaveAs(
        output_path, 0, 1, create_empty_dispatch_variant(), errors, warnings
    )

    ext = os.path.splitext(output_path)[1].upper()
    _print_result(ext, output_path, success, errors, warnings)
    return success


def _print_result(format_name, path, success, errors, warnings):
    """打印导出结果"""
    if success:
        print(f"{format_name} 导出成功: {path}")
    else:
        print(f"{format_name} 导出失败, 错误码: {errors.value}, 警告码: {warnings.value}")
