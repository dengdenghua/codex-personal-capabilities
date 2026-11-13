"""Declarative SolidWorks modelling engine driven by millimetre JSON plans.

This is the write-side counterpart to the inspection tools in worker.py.  It
reuses the validated COM helpers from the local solidworks-agentic-automation
skill, and it never overwrites an existing file: every plan produces NEW
artifacts that are verified against their own solid geometry before the caller
may treat the run as successful.

Plan units are millimetres and degrees.  SolidWorks works in metres and radians,
so every conversion happens inside this module.

A plan is data, not code:

    {
      "sketches": [
        {"plane": "Front Plane", "entities": [{"type": "circle", "cx": 0, "cy": 0, "r": 10}]}
      ],
      "features": [{"type": "extrude_boss", "sketch": 1, "depth": 25}],
      "verify": {"bodies": 1, "volume_mm3": 7853.98, "tolerance": 1e-4}
    }

Sketch references may be a 1-based index into "sketches" or a literal SolidWorks
sketch name returned by an earlier run.
"""
from __future__ import annotations

import functools
import math
from pathlib import Path

import pythoncom
import win32com.client as win32

from sw_connect import get_com_member as member, new_document, rebuild_document
from sw_part import (
    sketch as sketch_context,
    sketch_line,
    sketch_rectangle,
    sketch_corner_rectangle,
    sketch_circle,
    sketch_arc,
    sketch_polygon,
    sketch_slot,
    sketch_spline,
    _ensure_sketch_selected,
    _get_plane_name_candidates,
)
from sw_assembly import (
    add_component,
    add_mate_coincident,
    add_mate_concentric,
    add_mate_distance,
    add_mate_parallel,
    fix_component,
)
from sw_drawing import add_view, create_standard_views, add_note
from sw_export import export_to_step, export_to_stl, export_to_pdf

from portable_paths import templates
# Resolve the local template folder only when a default template is requested.
class _DefaultTemplates:
    names = {"part":"gb_part.prtdot","assembly":"gb_assembly.asmdot","drawing":"gb_a4.drwdot"}
    def __getitem__(self, kind): return templates()/self.names[kind]
DEFAULT_TEMPLATES = _DefaultTemplates()
DOC_TYPE = {"part": 1, "assembly": 2, "drawing": 3}

# swEndCondition_e
END_BLIND = 0
END_THROUGH_ALL = 1
END_MID_PLANE = 6


def _noop(*_args, **_kwargs):
    return None


# --------------------------------------------------------------------------
# unit + COM plumbing
# --------------------------------------------------------------------------

def _mm(value, field):
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number in millimetres: {value!r}")


def _rad(degrees, field):
    try:
        return float(degrees) * math.pi / 180.0
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number in degrees: {degrees!r}")


def _number(value, field):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number: {value!r}")


def _empty_dispatch():
    return win32.VARIANT(pythoncom.VT_DISPATCH, None)


def _byref_i4():
    return win32.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _output_path(name, suffix):
    path = Path(name)
    if not path.is_absolute():
        raise ValueError(f"Absolute output path required: {name}")
    if path.suffix.lower() != suffix:
        raise ValueError(f"Output must end with {suffix}: {name}")
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _require_units(plan):
    units = plan.get("units")
    if units is not None and str(units).lower() not in ("mm", "millimetre", "millimeter"):
        raise ValueError("Only millimetre plans are supported; omit 'units' or set it to 'mm'")


def _new_document(sw, kind, template):
    path = Path(template) if template else DEFAULT_TEMPLATES[kind]
    if not path.is_file():
        raise FileNotFoundError(f"{kind} template not found: {path}")
    doc = new_document(sw, kind, str(path))
    if doc is None:
        raise RuntimeError(f"Could not create a new {kind} document")
    _activate(sw, doc)
    return doc


def _activate(sw, doc):
    """Make the scratch document the active one, so sketch/feature selection
    cannot land on a different document the user already has open."""
    error = _byref_i4()
    result = sw.ActivateDoc3(str(member(doc, "GetTitle")), False, 0, error)
    if result is None or error.value:
        raise RuntimeError(f"Could not activate the scratch document: error {error.value}")
    return result


def _open_untitled_titles(sw):
    titles = []
    for doc in list(member(sw, "GetDocuments") or []):
        if not str(member(doc, "GetPathName") or "").strip():
            titles.append(str(member(doc, "GetTitle")))
    return titles


def _cleanup_scratch_on_failure(func):
    """Discard a partially built, never-saved scratch document when a plan fails.

    Only untitled documents that appeared during this call are discarded, so the
    user's own models are never touched.  Files already written to disk are kept.
    """
    @functools.wraps(func)
    def wrapper(sw, plan, output_path, stage=None):
        before = set(_open_untitled_titles(sw))
        try:
            return func(sw, plan, output_path, stage)
        except Exception as exc:
            for title in _open_untitled_titles(sw):
                if title in before:
                    continue
                try:
                    sw.QuitDoc(title)
                    exc.add_note(
                        f"Discarded partially built untitled document {title!r}; "
                        "no file was written for this plan."
                    )
                except Exception:
                    pass
            raise
    return wrapper


def _bodies(doc):
    return list(member(doc, "GetBodies2", 0, False) or [])


def _volume_m3(doc):
    total = 0.0
    for body in _bodies(doc):
        total += member(body, "GetMassProperties", 1)[3]
    return total


def _save_native(doc, path):
    errors = _byref_i4()
    warnings = _byref_i4()
    ok = doc.Extension.SaveAs(str(path), 0, 1, _empty_dispatch(), errors, warnings)
    if not ok or errors.value or not path.exists():
        raise RuntimeError(
            f"Save failed: return={ok}, errors={errors.value}, warnings={warnings.value}"
        )
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "errors": errors.value,
        "warnings": warnings.value,
    }


def _rebuild(doc):
    try:
        rebuild_document(doc)
    except Exception:
        pass
    bad = []
    try:
        count = int(member(doc.Extension, "GetWhatsWrongCount"))
        for index in range(min(count, 50)):
            try:
                bad.append(str(member(doc.Extension, "GetWhatsWrongAt", index)))
            except Exception:
                bad.append(f"unreadable item {index}")
    except Exception as exc:
        bad = [f"rebuild report unavailable: {exc}"]
    return {"whats_wrong_count": len(bad), "items": bad}


# --------------------------------------------------------------------------
# sketch entities (plan millimetres -> COM metres)
# --------------------------------------------------------------------------

def _entity_line(doc, entity):
    return sketch_line(
        doc,
        _mm(entity["x1"], "line.x1"), _mm(entity["y1"], "line.y1"),
        _mm(entity["x2"], "line.x2"), _mm(entity["y2"], "line.y2"),
    )


def _entity_rectangle(doc, entity):
    return sketch_rectangle(
        doc, _mm(entity["cx"], "rectangle.cx"), _mm(entity["cy"], "rectangle.cy"),
        _mm(entity["w"], "rectangle.w"), _mm(entity["h"], "rectangle.h"),
    )


def _entity_corner_rectangle(doc, entity):
    return sketch_corner_rectangle(
        doc,
        _mm(entity["x1"], "corner_rectangle.x1"), _mm(entity["y1"], "corner_rectangle.y1"),
        _mm(entity["x2"], "corner_rectangle.x2"), _mm(entity["y2"], "corner_rectangle.y2"),
    )


def _entity_circle(doc, entity):
    radius = entity.get("r")
    if radius is None:
        if entity.get("d") is None:
            raise ValueError("circle requires 'r' (or 'd')")
        radius = _number(entity["d"], "circle.d") / 2.0
    return sketch_circle(
        doc, _mm(entity["cx"], "circle.cx"), _mm(entity["cy"], "circle.cy"), _mm(radius, "circle.r")
    )


def _entity_arc(doc, entity):
    return sketch_arc(
        doc,
        _mm(entity["cx"], "arc.cx"), _mm(entity["cy"], "arc.cy"),
        _mm(entity["x1"], "arc.x1"), _mm(entity["y1"], "arc.y1"),
        _mm(entity["x2"], "arc.x2"), _mm(entity["y2"], "arc.y2"),
        int(entity.get("direction", 1)),
    )


def _entity_polygon(doc, entity):
    return sketch_polygon(
        doc, _mm(entity["cx"], "polygon.cx"), _mm(entity["cy"], "polygon.cy"),
        _mm(entity["r"], "polygon.r"), int(entity.get("sides", 6)),
    )


def _entity_slot(doc, entity):
    return sketch_slot(
        doc,
        _mm(entity["x1"], "slot.x1"), _mm(entity["y1"], "slot.y1"),
        _mm(entity["x2"], "slot.x2"), _mm(entity["y2"], "slot.y2"),
        _mm(entity["r"], "slot.r"),
    )


def _entity_spline(doc, entity):
    points = [(_mm(p[0], "spline.x"), _mm(p[1], "spline.y")) for p in entity["points"]]
    return sketch_spline(doc, points)


SKETCH_ENTITIES = {
    "line": _entity_line,
    "rectangle": _entity_rectangle,
    "corner_rectangle": _entity_corner_rectangle,
    "circle": _entity_circle,
    "arc": _entity_arc,
    "polygon": _entity_polygon,
    "slot": _entity_slot,
    "spline": _entity_spline,
}
# --------------------------------------------------------------------------
# entity selection
# --------------------------------------------------------------------------

def _point3(value):
    """Normalise a COM point/variant to a 3-tuple, or None when it is unusable."""
    try:
        candidate = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return candidate if len(candidate) == 3 else None


def _edge_probe_points(edge):
    points = []
    try:
        params = member(edge, "GetCurveParams2")
        if params and len(params) >= 6:
            for candidate in (
                (params[0], params[1], params[2]),
                (params[3], params[4], params[5]),
                tuple((params[i] + params[i + 3]) / 2.0 for i in range(3)),
            ):
                point = _point3(candidate)
                if point is not None:
                    points.append(point)
    except Exception:
        pass
    for accessor in ("GetStartVertex", "GetEndVertex"):
        try:
            vertex = member(edge, accessor)
            if vertex is not None:
                point = _point3(member(vertex, "GetPoint2"))
                if point is not None:
                    points.append(point)
        except Exception:
            pass
    return points


def _edge_distance_to(edge, target):
    points = list(_edge_probe_points(edge))
    try:
        closest = _point3(member(edge, "GetClosestPointOn", target[0], target[1], target[2]))
        if closest is not None:
            points.append(closest)
    except Exception:
        pass
    usable = [point for point in points if len(point) == 3]
    if not usable:
        return None
    return min(math.dist(point, target) for point in usable)


def _all_edges(doc):
    edges = []
    for body in _bodies(doc):
        edges.extend(list(member(body, "GetEdges") or []))
    return edges


def _select_edges(doc, selector, field="edges"):
    """selector: "all" or a list of {"point": [x, y, z]} picks resolved by nearest edge."""
    doc.ClearSelection2(True)
    if selector in (None, "none"):
        return 0
    if selector == "all":
        selected = 0
        for edge in _all_edges(doc):
            if edge.Select4(True, _empty_dispatch()):
                selected += 1
        if not selected:
            raise RuntimeError("No edges available to select")
        return selected
    if isinstance(selector, dict):
        selector = [selector]
    if not isinstance(selector, list) or not selector:
        raise ValueError(f"{field} must be 'all' or a non-empty list of point picks")
    edges = _all_edges(doc)
    if not edges:
        raise RuntimeError("No edges available to select")
    selected = 0
    for pick in selector:
        target = tuple(_mm(value, f"{field}.point") for value in pick["point"])
        scored = []
        for edge in edges:
            distance = _edge_distance_to(edge, target)
            if distance is not None:
                scored.append((distance, edge))
        if not scored:
            raise RuntimeError(f"No selectable edge near {pick['point']}")
        scored.sort(key=lambda item: item[0])
        distance, edge = scored[0]
        if not edge.Select4(True, _empty_dispatch()):
            raise RuntimeError(f"Edge selection rejected near {pick['point']}")
        selected += 1
    return selected


def _all_faces(doc):
    faces = []
    for body in _bodies(doc):
        faces.extend(list(member(body, "GetFaces") or []))
    return faces


def _face_center(face):
    try:
        box = member(face, "GetBox")
        return tuple((box[i] + box[i + 3]) / 2.0 for i in range(3))
    except Exception:
        return None


def _select_faces(doc, selector, field="faces"):
    """selector: "all" or a list of {"point": [x, y, z]} picks resolved by nearest face."""
    doc.ClearSelection2(True)
    if selector in (None, "none"):
        return 0
    faces = _all_faces(doc)
    if not faces:
        raise RuntimeError("No faces available to select")
    if selector == "all":
        for face in faces:
            face.Select4(True, _empty_dispatch())
        return len(faces)
    if isinstance(selector, dict):
        selector = [selector]
    if not isinstance(selector, list) or not selector:
        raise ValueError(f"{field} must be 'all' or a non-empty list of point picks")
    selected = 0
    for pick in selector:
        target = tuple(_mm(value, f"{field}.point") for value in pick["point"])
        best = None
        for face in faces:
            try:
                closest = _point3(member(face, "GetClosestPointOn", target[0], target[1], target[2]))
                if closest is None:
                    raise ValueError("unusable closest point")
                distance = math.dist(closest, target)
            except Exception:
                center = _face_center(face)
                if center is None:
                    continue
                distance = math.dist(center, target)
            if best is None or distance < best[0]:
                best = (distance, face)
        if best is None:
            raise RuntimeError(f"No selectable face near {pick['point']}")
        if not best[1].Select4(True, _empty_dispatch()):
            raise RuntimeError(f"Face selection rejected near {pick['point']}")
        selected += 1
    return selected
# --------------------------------------------------------------------------
# part features
# --------------------------------------------------------------------------

def _sketch_reference(feature, sketch_names):
    reference = feature.get("sketch")
    if reference is None:
        raise ValueError("Feature requires a 'sketch' reference (1-based index or sketch name)")
    if isinstance(reference, bool):
        raise ValueError("Feature 'sketch' must be an index or a name, not a boolean")
    if isinstance(reference, int):
        if not 1 <= reference <= len(sketch_names):
            raise ValueError(
                f"Feature 'sketch' index {reference} is out of range 1..{len(sketch_names)}"
            )
        return sketch_names[reference - 1]
    return str(reference)


def _resolve_feature_ref(feature, feature_names):
    """Patterns and mirrors may target an earlier feature by 1-based index or by name."""
    reference = feature.get("feature")
    if reference is None:
        reference = feature.get("feature_name")
    if reference is None:
        return None
    if isinstance(reference, bool):
        raise ValueError("'feature' must be an index or a name, not a boolean")
    if isinstance(reference, int):
        if not feature_names or not 1 <= reference <= len(feature_names):
            raise ValueError(
                f"'feature' index {reference} does not match an earlier feature in this plan "
                f"(1..{len(feature_names or [])})"
            )
        return feature_names[reference - 1]
    return str(reference)


def _extrude(doc, sketch_name, depth_m, direction, flip, merge, end_condition):
    # clear stale feature selection: SolidWorks leaves the new feature selected,
    # and _ensure_sketch_selected would otherwise reuse that selection.
    doc.ClearSelection2(True)
    _ensure_sketch_selected(doc, sketch_name)
    return doc.FeatureManager.FeatureExtrusion3(
        True, bool(flip), bool(direction),
        end_condition, 0,
        depth_m, 0.0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        bool(merge), False, True,
        0, 0.0, False,
    )


def _feature_extrude_boss(doc, feature, sketch_names, feature_names=None):
    name = _sketch_reference(feature, sketch_names)
    through_all = bool(feature.get("through_all", False))
    depth = 0.0 if through_all else _mm(feature.get("depth"), "extrude_boss.depth")
    if not through_all and depth <= 0:
        raise ValueError("extrude_boss.depth must be > 0 mm unless through_all is true")
    return _extrude(
        doc, name, depth,
        bool(feature.get("direction", True)),
        bool(feature.get("flip", False)),
        bool(feature.get("merge", True)),
        END_THROUGH_ALL if through_all else END_BLIND,
    )


def _feature_extrude_cut(doc, feature, sketch_names, feature_names=None):
    name = _sketch_reference(feature, sketch_names)
    through_all = bool(feature.get("through_all", False))
    depth = 0.0 if through_all else _mm(feature.get("depth"), "extrude_cut.depth")
    if not through_all and depth <= 0:
        raise ValueError("extrude_cut.depth must be > 0 mm unless through_all is true")
    doc.ClearSelection2(True)
    _ensure_sketch_selected(doc, name)
    return doc.FeatureManager.FeatureCut4(
        bool(feature.get("direction", True)), bool(feature.get("flip", False)), False,
        END_THROUGH_ALL if through_all else END_BLIND, 0,
        depth if not through_all else 0.01, 0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False, False,
        True, True, True, True,
        False, 0, 0, False, False,
    )


def _feature_extrude_midplane(doc, feature, sketch_names, feature_names=None):
    name = _sketch_reference(feature, sketch_names)
    total = _mm(feature.get("total_depth", feature.get("depth")), "extrude_midplane.total_depth")
    if total <= 0:
        raise ValueError("extrude_midplane.total_depth must be > 0 mm")
    doc.ClearSelection2(True)
    _ensure_sketch_selected(doc, name)
    return doc.FeatureManager.FeatureExtrusion3(
        True, False, True,
        END_MID_PLANE, 0,
        total, 0.0,
        False, False, False, False,
        0.0, 0.0,
        False, False, False, False,
        bool(feature.get("merge", True)), False, True,
        0, 0.0, False,
    )


def _feature_fillet(doc, feature, _sketch_names, feature_names=None):
    radius = _mm(feature.get("radius"), "fillet.radius")
    if radius <= 0:
        raise ValueError("fillet.radius must be > 0 mm")
    _select_edges(doc, feature.get("edges", "all"), "fillet.edges")
    result = doc.FeatureManager.FeatureFillet(195, radius, 0, 0, None, None, None)
    doc.ClearSelection2(True)
    return result


def _feature_chamfer(doc, feature, _sketch_names, feature_names=None):
    distance = _mm(feature.get("distance"), "chamfer.distance")
    if distance <= 0:
        raise ValueError("chamfer.distance must be > 0 mm")
    angle = _rad(feature.get("angle_deg", 45), "chamfer.angle_deg")
    _select_edges(doc, feature.get("edges", "all"), "chamfer.edges")
    result = doc.FeatureManager.InsertFeatureChamfer(4, 1, distance, angle, 0, 0, 0, 0)
    doc.ClearSelection2(True)
    return result


def _feature_shell(doc, feature, _sketch_names, feature_names=None):
    thickness = _mm(feature.get("thickness"), "shell.thickness")
    if thickness <= 0:
        raise ValueError("shell.thickness must be > 0 mm")
    faces = feature.get("faces", "none")
    if faces not in (None, "none"):
        _select_faces(doc, faces, "shell.faces")
    # Shell lives on IModelDoc2 in SOLIDWORKS 2026 and returns no feature object,
    # so success is confirmed by the feature count instead of the return value.
    before = int(member(doc.FeatureManager, "GetFeatureCount", True))
    doc.InsertFeatureShell(thickness, False)
    doc.ClearSelection2(True)
    after = int(member(doc.FeatureManager, "GetFeatureCount", True))
    return True if after > before else None


def _feature_linear_pattern(doc, feature, _sketch_names, feature_names=None):
    """Not supported: FeatureLinearPattern3 returns False and changes nothing here.

    Verified: feature count and volume are unchanged and no error is raised, so a
    caller could mistake it for success.  Refuse instead of returning a wrong part.
    """
    raise RuntimeError(
        "linear_pattern is not supported on this SOLIDWORKS build: FeatureLinearPattern3 returns "
        "False and modifies nothing (verified: identical feature count and volume, no error "
        "reported). Put every repeated entity in ONE sketch instead - that is supported and "
        "verified (a 3-hole array built this way matched the analytic volume exactly)."
    )


def _feature_circular_pattern(doc, feature, _sketch_names, feature_names=None):
    """Not supported: FeatureCircularPattern4 is not reliable on this build.

    No verified circular-pattern call exists here, so refuse rather than emit a
    part that silently lacks the pattern.
    """
    raise RuntimeError(
        "circular_pattern is not supported on this SOLIDWORKS build. Put every repeated entity "
        "in ONE sketch instead - that is supported and verified. For a bolt circle, draw the "
        "circle positions directly with one 'circle' entity each."
    )


def _feature_mirror(doc, feature, _sketch_names, feature_names=None):
    """Not supported: InsertMirrorFeature2 returns False and changes nothing here.

    Feature count and volume stay identical, so this build cannot mirror through
    late binding.  Modelling it by hand produces a wrong part silently, so refuse.
    """
    raise RuntimeError(
        "mirror_feature is not supported on this SOLIDWORKS build: InsertMirrorFeature2 returns "
        "False and modifies nothing (verified: identical feature count and volume, no error "
        "reported). Draw the mirrored profile in the same sketch instead - arbitrary symmetric "
        "geometry in one sketch is supported and verified."
    )


PART_FEATURES = {
    "extrude_boss": _feature_extrude_boss,
    "extrude_cut": _feature_extrude_cut,
    "extrude_midplane": _feature_extrude_midplane,
    "fillet": _feature_fillet,
    "chamfer": _feature_chamfer,
    "shell": _feature_shell,
    "linear_pattern": _feature_linear_pattern,
    "circular_pattern": _feature_circular_pattern,
    "mirror_feature": _feature_mirror,
}
# --------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------

@_cleanup_scratch_on_failure
def create_part(sw, plan, output_path, stage=None):
    stage = stage or _noop
    _require_units(plan)
    target = _output_path(output_path, ".sldprt")
    doc = _new_document(sw, "part", plan.get("template"))
    stage("part_created", {"template": str(plan.get("template") or DEFAULT_TEMPLATES["part"])})

    sketch_names = []
    for index, sketch_plan in enumerate(plan.get("sketches") or [], start=1):
        entities = sketch_plan.get("entities") or []
        if not entities:
            raise ValueError(f"Sketch {index} has no entities")
        plane = sketch_plan.get("plane") or "Front Plane"
        with sketch_context(doc, plane) as name:
            for entity_index, entity in enumerate(entities, start=1):
                kind = str(entity.get("type") or "").lower()
                handler = SKETCH_ENTITIES.get(kind)
                if handler is None:
                    raise ValueError(
                        f"Sketch {index} entity {entity_index}: unsupported type {kind!r}; "
                        f"supported: {sorted(SKETCH_ENTITIES)}"
                    )
                created = handler(doc, entity)
                if created is None:
                    raise RuntimeError(
                        f"Sketch {index} entity {entity_index} ({kind}) was not created"
                    )
        sketch_names.append(name)
        stage("sketch", {"index": index, "name": name, "plane": plane, "entities": len(entities)})

    applied = []
    feature_names = []
    for index, feature in enumerate(plan.get("features") or [], start=1):
        kind = str(feature.get("type") or "").lower()
        handler = PART_FEATURES.get(kind)
        if handler is None:
            raise ValueError(
                f"Feature {index}: unsupported type {kind!r}; supported: {sorted(PART_FEATURES)}"
            )
        created = handler(doc, feature, sketch_names, feature_names)
        if created is None:
            raise RuntimeError(f"Feature {index} ({kind}) returned no feature; model not built")
        try:
            actual_name = str(member(created, "Name"))
        except Exception:
            actual_name = ""
        feature_names.append(actual_name)
        applied.append({"index": index, "type": kind, "name": actual_name})
        stage("feature", {"index": index, "type": kind})

    doc.ClearSelection2(True)
    rebuild = _rebuild(doc)
    bodies = _bodies(doc)
    volume_m3 = _volume_m3(doc)

    verification = _verify_part(plan.get("verify") or {}, len(bodies), volume_m3)
    save = _save_native(doc, target)
    exports = _export_artifacts(doc, plan.get("exports") or [], target)

    return {
        "document": {"title": member(doc, "GetTitle"), "path": member(doc, "GetPathName")},
        "sketch_names": sketch_names,
        "features_applied": applied,
        "solid_bodies": len(bodies),
        "volume_mm3": round(volume_m3 * 1e9, 6),
        "body_bounds_mm": [
            [round(value * 1000.0, 6) for value in member(body, "GetBodyBox")] for body in bodies[:50]
        ],
        "rebuild": rebuild,
        "save": save,
        "exports": exports,
        "verification": verification,
        "verified": bool(verification["passed"] and rebuild["whats_wrong_count"] == 0),
    }


def _verify_part(expect, body_count, volume_m3):
    result = {"expect": expect, "passed": True, "checks": []}
    expected_bodies = expect.get("bodies")
    if expected_bodies is not None:
        ok = int(expected_bodies) == body_count
        result["checks"].append(
            {"check": "bodies", "expected": int(expected_bodies), "actual": body_count, "passed": ok}
        )
        result["passed"] = result["passed"] and ok
    expected_volume = expect.get("volume_mm3")
    if expected_volume is not None:
        tolerance = float(expect.get("tolerance", 1e-3))
        actual_mm3 = volume_m3 * 1e9
        target = float(expected_volume)
        relative = abs(actual_mm3 - target) / target if target else float("inf")
        ok = relative <= tolerance
        result["checks"].append({
            "check": "volume_mm3", "expected": target, "actual": round(actual_mm3, 6),
            "relative_error": relative, "tolerance": tolerance, "passed": ok,
        })
        result["passed"] = result["passed"] and ok
    if not result["checks"]:
        result["passed"] = False
        result["note"] = (
            "No verification block supplied; geometry was measured but not compared to an expectation."
        )
    return result


def _export_artifacts(doc, exports, native_path):
    results = []
    for item in exports:
        fmt = str(item.get("format") or "").lower()
        suffix = {"step": ".step", "stp": ".step", "stl": ".stl", "pdf": ".pdf"}.get(fmt)
        if suffix is None:
            raise ValueError(f"Unsupported export format {fmt!r}; supported: step, stl, pdf")
        path = _output_path(item.get("path") or str(native_path.with_suffix(suffix)), suffix)
        if suffix == ".step":
            ok = export_to_step(doc, str(path))
        elif suffix == ".stl":
            ok = export_to_stl(doc, str(path), item.get("quality", "fine"))
        else:
            ok = export_to_pdf(doc, str(path), item.get("sheets"))
        results.append({
            "format": fmt,
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "reported_success": bool(ok),
        })
    return results


@_cleanup_scratch_on_failure
def create_assembly(sw, plan, output_path, stage=None):
    stage = stage or _noop
    _require_units(plan)
    target = _output_path(output_path, ".sldasm")
    doc = _new_document(sw, "assembly", plan.get("template"))

    components = plan.get("components") or []
    if not components:
        raise ValueError("Assembly plan requires at least one component")
    placed = []
    for index, item in enumerate(components, start=1):
        part = Path(item["part"])
        if not part.is_file():
            raise FileNotFoundError(f"Component {index} not found: {part}")
        component = add_component(
            doc, str(part),
            _mm(item.get("x", 0), f"components[{index}].x"),
            _mm(item.get("y", 0), f"components[{index}].y"),
            _mm(item.get("z", 0), f"components[{index}].z"),
            str(item.get("config", "")),
        )
        if component is None:
            raise RuntimeError(f"Component {index} could not be added: {part}")
        if item.get("fix"):
            fix_component(doc, component)
        placed.append(
            {"name": str(member(component, "Name2")), "path": str(part), "fixed": bool(item.get("fix"))}
        )
        stage("component", {"index": index, "name": placed[-1]["name"]})

    mate_handlers = {
        "coincident": add_mate_coincident,
        "concentric": add_mate_concentric,
        "distance": add_mate_distance,
        "parallel": add_mate_parallel,
    }
    mates_applied = []
    for index, mate in enumerate(plan.get("mates") or [], start=1):
        kind = str(mate.get("type") or "").lower()
        handler = mate_handlers.get(kind)
        if handler is None:
            raise ValueError(f"Mate {index}: unsupported type {kind!r}; supported: {sorted(mate_handlers)}")
        first, second = mate.get("entity1"), mate.get("entity2")
        if not first or not second:
            raise ValueError(f"Mate {index} requires 'entity1' and 'entity2'")
        extra = ()
        if kind == "distance":
            extra = (_mm(mate["distance"], f"mates[{index}].distance"),)
        result = handler(
            doc,
            str(first), str(mate.get("entity1_type") or "FACE"),
            str(second), str(mate.get("entity2_type") or "FACE"),
            *extra,
        )
        if result is None:
            raise RuntimeError(f"Mate {index} ({kind}) failed between {first} and {second}")
        mates_applied.append({"index": index, "type": kind, "entity1": str(first), "entity2": str(second)})
        stage("mate", {"index": index, "type": kind})

    doc.ClearSelection2(True)
    rebuild = _rebuild(doc)
    top = list(member(doc, "GetComponents", True) or [])
    save = _save_native(doc, target)
    exports = _export_artifacts(doc, plan.get("exports") or [], target)

    return {
        "document": {"title": member(doc, "GetTitle"), "path": member(doc, "GetPathName")},
        "components": placed,
        "mates_applied": mates_applied,
        "top_level_components": len(top),
        "rebuild": rebuild,
        "save": save,
        "exports": exports,
        "verified": bool(rebuild["whats_wrong_count"] == 0 and len(top) == len(components)),
        "note": (
            "Mate error codes are not read here; run sw_mate_status on the saved assembly "
            "before trusting the fit."
        ),
    }


@_cleanup_scratch_on_failure
def create_drawing(sw, plan, output_path, stage=None):
    stage = stage or _noop
    _require_units(plan)
    target = _output_path(output_path, ".slddrw")
    source = plan.get("part")
    if not source:
        raise ValueError("Drawing plan requires 'part' (the model to draw)")
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Drawn model not found: {source_path}")

    doc = _new_document(sw, "drawing", plan.get("template"))
    stage("drawing_created", {"part": str(source_path)})

    views = plan.get("views")
    placed = []
    if views is None:
        placed.append({"type": "standard", "reported": str(create_standard_views(doc, str(source_path)))})
    else:
        for index, view in enumerate(views, start=1):
            kind = str(view.get("type") or "").lower()
            if kind in ("standard", "standard_views"):
                placed.append({
                    "index": index, "type": "standard",
                    "reported": str(create_standard_views(doc, str(source_path))),
                })
                continue
            created = add_view(
                doc, str(source_path), kind,
                _mm(view.get("x", 200), f"views[{index}].x"),
                _mm(view.get("y", 150), f"views[{index}].y"),
                _number(view["scale"], f"views[{index}].scale") if view.get("scale") else None,
            )
            placed.append({"index": index, "type": kind, "created": created is not None})
            stage("view", {"index": index, "type": kind})

    for index, note in enumerate(plan.get("notes") or [], start=1):
        add_note(
            doc,
            _mm(note.get("x", 10), f"notes[{index}].x"),
            _mm(note.get("y", 10), f"notes[{index}].y"),
            str(note.get("text") or ""),
        )

    doc.ClearSelection2(True)
    rebuild = _rebuild(doc)
    save = _save_native(doc, target)
    exports = _export_artifacts(doc, plan.get("exports") or [], target)

    return {
        "document": {"title": member(doc, "GetTitle"), "path": member(doc, "GetPathName")},
        "views": placed,
        "notes": len(plan.get("notes") or []),
        "rebuild": rebuild,
        "save": save,
        "exports": exports,
        "verified": bool(rebuild["whats_wrong_count"] == 0),
    }
