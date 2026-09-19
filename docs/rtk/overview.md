RTK Integration Notes
=====================

This project includes helpers to install and initialize RTK (Rust Token Killer) for token-optimized shell outputs.

Install
-------
- Linux/macOS: `scripts/rtk/install_rtk.sh` (requires `jq` and `curl`)
- Windows (PowerShell): `scripts/rtk/install_rtk.ps1`

Project init
------------
After installing RTK, run:

```bash
# from repo root
.tools/rtk/rtk init -g --copilot
# or if installed system-wide
rtk init -g --copilot
```

CI / Template
-------------
Consider adding `.tools/rtk` to your CI runners or using the `rtk` binary directly in scripts to ensure consistent behavior across environments.

Usage in scripts
----------------
Replace heavy outputs when sending to LLMs with `rtk` wrappers, e.g. `rtk read`, `rtk grep`, `rtk pytest` to reduce tokens.
