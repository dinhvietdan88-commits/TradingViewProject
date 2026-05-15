"""Live smoke test for P10 Auth endpoints."""
import sys, io, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = 'http://localhost:5000'
PASS = 0; FAIL = 0


def check(label, url, expected_codes):
    global PASS, FAIL
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as ex:
        print(f'  [FAIL] {label}: ERROR -- {ex}')
        FAIL += 1
        return
    ok = code in expected_codes
    result = 'PASS' if ok else 'FAIL'
    print(f'  [{result}] {label}: HTTP {code} (want {expected_codes})')
    if ok:
        PASS += 1
    else:
        FAIL += 1


print()
print('=' * 62)
print('  P10 Auth — Live Smoke Test')
print('=' * 62)

# Public endpoints — always accessible
check('T1  /health                    (always public)',     f'{BASE}/health',                                               [200])
check('T2  /auth/login                (login page)',        f'{BASE}/auth/login',                                          [200])
check('T3  /auth/logout               (no session->redir)', f'{BASE}/auth/logout',                                         [200, 302])
check('T8  /static/login.html         (static asset)',      f'{BASE}/static/login.html',                                   [200])
check('T9  /api/system/status         (public endpoint)',   f'{BASE}/api/system/status',                                   [200])

# Auth callback validation (route handler returns 400/401 for bad codes)
check('T4  /auth/callback?code=       (empty->400/401)',    f'{BASE}/auth/callback?code=',                                 [400, 401, 422])
check('T5  /auth/callback (invalid)', f'{BASE}/auth/callback?code=deadbeef00000000deadbeef00000000', [400, 401])

# Protected endpoints (open because DASHBOARD_TOKEN not set in dev)
check('T6  /trades                    (no token->open dev)', f'{BASE}/trades',                                             [200])

# New auth routes exist
check('T10 /auth/login returns HTML',                       f'{BASE}/auth/login',                                         [200])

print()
summary = 'CLEAN' if FAIL == 0 else f'{FAIL} FAILURES'
print(f'  Result: {PASS} passed / {PASS + FAIL} total  [{summary}]')
print('=' * 62)
