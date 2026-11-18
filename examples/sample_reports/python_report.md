# Modernizer migration report

## legacy_py (python)

| files scanned | files changed | auto rewrites | needs review | repair rounds | seconds |
|---|---|---|---|---|---|
| 4 | 2 | 2 | 1 | 0 | 0.33 |

**Before (original code)**

- `compile`: FAIL — app/core.py:16: Missing parentheses in call to 'print'. Did you mean print(...)?
- `tests`: skipped — skipped: fix compile errors first

**After migration**

- `compile`: pass
- `tests`: pass

### Applied automatically

- `2to3` x2

### Needs human review

- **py3-string-module** x1 — these string-module functions/constants were removed; use str methods or string.ascii_letters
    - `app/util.py:9`
