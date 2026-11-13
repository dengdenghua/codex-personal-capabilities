# COM Survival Guide

## Selection is state

Most feature failures begin with a wrong or incomplete selection. Log entity names,
entity types, selection marks, coordinates, each `Select*` return value, and the selected
object count. Clear the selection before and after a fragile operation.

Prefer returned COM objects over localized feature names. When names are unavoidable,
read the real `ActiveSketch.Name` or feature-tree name instead of predicting `Sketch7`.

## Explicit types

Long COM signatures require the documented argument count and types. Use explicit
`VARIANT` values for by-ref integers, dispatch placeholders, and numeric arrays. Verify
the official API help or local SDK for methods that are not already wrapped.

pywin32 `CDispatch` objects are callable even when they were already returned by a COM
property. Use `get_com_member()` instead of blindly calling every member whose Python
`callable()` result is true; otherwise the object's default member may raise a misleading
"member not found" error.

## Rebuild and body checks

A non-null feature is necessary but not sufficient. Run `rebuild_document(model)`; this
handles environments where dynamic dispatch exposes `EditRebuild3` as a boolean property
instead of a callable method. Inspect feature errors and suppression, and compare body count to
the case contract. A neutral export can succeed from a stale or unintended geometry.

## Paths and encodings

Use UTF-8 `.py` files for long commands or non-ASCII paths. Keep temporary review output
under a short path if a legacy API rejects a valid long path. Write evidence JSON with
`ensure_ascii=True`, parse it before replacement, and retain the original artifact path in
the report.

## Long operations and dialogs

Before declaring a rebuild frozen, inspect CPU activity, logs, output timestamps, the
SolidWorks status bar, and modal dialogs. Do not open a second instance while the first is
actively rebuilding. If a dialog blocks automation, capture its title/message and resolve
that specific condition.

## Historical feature trees

Changing a pattern instance count or replacing a parent feature can invalidate downstream
references. Treat topology-changing parameters as discrete model families. Create a
working copy, preserve interfaces, regenerate dependent features when necessary, and
compare the final envelope and previews to the source.
