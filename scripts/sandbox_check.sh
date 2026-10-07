#!/bin/sh
# Pre-flight for running ItDA inside the OpenShell sandbox. Read-only; changes nothing.
#   sh scripts/sandbox_check.sh
SB=${SANDBOX:-itda-hack}
X="openshell sandbox exec -n $SB --"
echo "== 1. model route from Python inside the sandbox (inference.local, no API key in sandbox)"
$X python3 -c "
import json, urllib.request
for u in ('https://inference.local/v1/models', 'http://inference.local/v1/models'):
    try:
        d = json.load(urllib.request.urlopen(u, timeout=15)); print('OK', u, [m['id'] for m in d.get('data', [])][:4]); break
    except Exception as e:
        print('FAIL', u, type(e).__name__, str(e)[:120])
"
echo "== 2. API key visible inside the sandbox? (should be none or a placeholder)"
$X sh -c 'env | grep -iE "api_key|token|secret" | sed -E "s/=(.{6}).*/=\1***/" || echo "(no key-like env vars)"'
echo "== 3. egress to a random site (should be blocked)"
$X curl -sS -m 10 -o /dev/null -w "example.com -> %{http_code}\n" https://example.com
echo "== 4. active network policies"
openshell policy get "$SB" --full | grep -E "^  [a-z_]+:$"
