# RTK integration (Quick Start)

This repository includes a helper to initialize RTK scaffolding for this project.

Quick steps

- Install RTK CLI per the project: https://github.com/rtk-ai/rtk
- From the repository root run:

```bash
python scripts/rtk/setup_rtk.py --generator copilot
```

Notes

- The helper script checks whether `rtk` is available on `PATH`. If not found it prints common install hints and the upstream URL.
- Adjust `--generator` to the desired generator (for example `copilot` as in the Quick Start).
- After running `rtk init` review the generated files and commit them alongside your changes.

If you want, I can try to run `rtk init -g copilot` locally now — you will need to have the `rtk` CLI installed on this machine.
