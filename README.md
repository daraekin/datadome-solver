# Generic DataDome Bypass (Python, open source)

Pure Python DataDome cookie generator — works on **any** DataDome-protected website.

Posts realistic Chrome browser fingerprints to `api-js.datadome.co/js/` with Chrome TLS impersonation (curl_cffi). Falls back to Zendriver headless Chrome for full jspl blob bypass.

## Features

- **Pure HTTP solver:** CH + LE cookie generation (works for main pages + tokenize endpoints)
- **Browser fallback:** Zendriver CDP-based solver captures real DataDome cookies + full sessions
- **Generic:** DDK auto-detection from target site
- **curl_cffi TLS:** Chrome impersonation (no JA3 fingerprinting)
- **harvest.py:** Generates storage-state.json session files for any engine

| Feature | Status |
|---|---|
| DDK auto-detection | ✅ |
| CH cookie (challenge) | ✅ |
| LE cookie (logged events) | ✅ |
| Main page bypass | ✅ |
| API tokenize bypass | ✅ |
| API submit bypass | ⚠️ Browser fallback required |

## Installation

```bash
pip install curl_cffi zendriver
playwright install chromium  # only for browser fallback
```

## Usage

```python
from solver import DataDomeSolver

solver = DataDomeSolver(
    target_url="https://target-site.com/page",
    ddk="F2F61859A3070DEFFC633C1880FE37"  # auto-detect or manual
)
cookie = solver.solve()
print(cookie["value"])  # Valid datadome cookie
```

## CLI

```bash
python solver.py https://target-site.com [DDK]
```

## Architecture

```
solver.py           — Pure HTTP CH+LE cookie generation
browser_capture.py  — Zendriver headless Chrome capture (jspl bypass)
harvest.py          — Session harvester using solver
```

## Credits

- [gravilk/datadome-documented](https://github.com/gravilk/datadome-documented)
- [ellisfan/bypass-datadome](https://github.com/ellisfan/bypass-datadome)

## License

MIT
