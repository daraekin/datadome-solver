# Generic DataDome Bypass (HTTP-only, no browser)

Pure Python DataDome cookie generator — works on **any** DataDome-protected website.

Posts realistic Chrome browser fingerprints to `api-js.datadome.co/js/` using `curl_cffi` TLS impersonation. No browser, no captcha solving service needed.

## Features

- **Generic:** Works on any DataDome-protected site (auto-detects site key)
- **No browser:** Pure HTTP — 200-400ms per cookie
- **CH + LE support:** Challenge + Logged Events (mouse behavior simulation)
- **TLS impersonation:** Chrome 124 via curl_cffi (no JA3 fingerprinting)
- **Proxy support:** Works through residential/datacenter proxies

## Installation

```bash
pip install curl_cffi
```

## Quick Start

```python
from solver import DataDomeSolver

# Auto-detect everything
solver = DataDomeSolver(target_url="https://secure.qgiv.com/for/campaign")
cookie = solver.solve()
print(cookie["value"])  # Valid datadome cookie

# With manual DDK
solver = DataDomeSolver(
    target_url="https://target-site.com/page",
    ddk="F2F61859A3070DEFFC633C1880FE37",
    proxy="http://user:pass@host:port"
)
cookie = solver.solve()
```

## CLI

```bash
# Auto-detect DDK
python solver.py https://target-site.com

# With manual DDK
python solver.py https://target-site.com F2F61859A3070DEFFC633C1880FE37

# Harvest sessions
set TARGET_URL=https://target-site.com
set HARVEST_COUNT=5
python harvest.py
```

## How It Works

1. **DDK extraction:** Visits target page, extracts `hsh` from 403 `dd={}` JSON or finds `tags.js` URL
2. **CH cookie:** Builds realistic Chrome fingerprint (screen, GPU, plugins, codecs, timezone) → POST to `api-js.datadome.co/js/` → gets datadome cookie
3. **LE cookie:** Adds simulated mouse movement + behavior data (click counts, scroll, movement metrics) → POST again → gets validated datadome cookie
4. **Session pairing:** Visits target site with the cookie to get matching PHPSESSID → saves as `storage-state.json`

## Credits

Reverse-engineered DataDome internals from:
- [gravilk/datadome-documented](https://github.com/gravilk/datadome-documented) — deobfuscated JS + field documentation
- [ellisfan/bypass-datadome](https://github.com/ellisfan/bypass-datadome) — Python fingerprint builder pattern

## License

MIT
