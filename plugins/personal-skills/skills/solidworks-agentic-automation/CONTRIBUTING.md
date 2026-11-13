# Contributing

Contributions should improve the reusable SolidWorks automation pattern rather than add a
single private model generator to the core.

## Bug reports

Include the SolidWorks, Windows, Python, pywin32, and comtypes versions; the smallest
reproducible script; the exact COM error or return value; UI language; and whether the
failure reproduces from a clean document.

Do not attach proprietary CAD, credentials, private paths, papers, or experiment data.
Create an anonymous minimal part whenever possible.

## Pull requests

1. Add or update a focused helper or reference document.
2. Preserve backward compatibility unless the change fixes a proven defect.
3. Add an offline unit test for logic that does not require SolidWorks.
4. Run `python scripts/validate_skill.py` and `python -m pytest`.
5. For COM changes, run a one-instance SolidWorks smoke test and attach the evidence JSON,
   return/error codes, and anonymous previews.
6. Document version-specific behavior and link the relevant official API signature.

## Design rules

- Keep project-specific geometry, dimensions, and CAE settings in separate adapters.
- Check COM return values; do not convert failures into success messages.
- Never terminate an existing SolidWorks or ANSYS process automatically.
- Preserve user source files and write generated artifacts to a working directory.
- Prefer returned COM objects to guessed localized feature names.
- Treat preview inspection as part of acceptance, not decoration.

## Commit style

Use a short imperative summary such as `Add atomic CAD evidence recorder` or
`Fix AddMate5 error-status validation`.
