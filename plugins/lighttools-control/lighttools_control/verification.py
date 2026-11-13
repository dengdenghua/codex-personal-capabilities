"""Explicit readback assertions; a successful native status is not equality."""
import math


def check_values(session, checks, rel_tol=1e-8, abs_tol=1e-9):
    if not checks or len(checks) > 50:
        raise ValueError('Provide 1 to 50 checks')
    if not all(math.isfinite(x) and x >= 0 for x in (rel_tol, abs_tol)):
        raise ValueError('Tolerances must be finite and nonnegative')
    for c in checks:
        if not isinstance(c.get('key'), str) or not c['key'].strip() or not isinstance(c.get('field'), str) or not c['field'].strip():
            raise ValueError('Every check requires a nonblank key and field')
        expected = c['expected']
        if type(expected) not in (str, bool, float, int) or (type(expected) in (float, int) and not math.isfinite(expected)):
            raise ValueError('Expected values must be finite scalars')
    results = []
    for c in checks:
        actual = session.get(c['key'], c['field'], c.get('i', -1), c.get('j', -1))
        expected = c['expected']
        numeric = type(expected) in (float, int) and type(actual) in (float, int)
        matched = (math.isfinite(actual) and math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol)
                   if numeric else type(actual) is type(expected) and actual == expected)
        results.append({**c, 'actual': actual, 'matched': matched})
    return {'verified': all(c['matched'] for c in results), 'checks': results,
            'rel_tol': rel_tol, 'abs_tol': abs_tol}
