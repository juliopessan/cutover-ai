RTK Installation Guide - For AI Coding Assistants
================================================

⚠️ Name Collision Warning

There are TWO completely different projects named "rtk":

- ✅ Rust Token Killer (this project) - LLM token optimizer
  - Repos: rtk-ai/rtk
  - Has `rtk gain` command for token savings stats

- ❌ Rust Type Kit (reachingforthejack/rtk) - DIFFERENT PROJECT
  - Rust codebase query tool and type generator

DO NOT install if you want token optimization

Pre-Installation Check (REQUIRED)

AI assistants should ALWAYS verify if RTK is already installed before attempting installation.

```bash
# Check if RTK is installed
rtk --version

# CRITICAL: Verify it's the Token Killer (not Type Kit)
rtk gain    # Should show token savings stats, NOT "command not found"

# Check installation path
which rtk
```

If `rtk gain` works, you have the correct RTK installed. DO NOT reinstall. Skip to "Project Initialization".
If `rtk gain` fails but `rtk --version` succeeds, you have the wrong RTK (Type Kit). Uninstall and reinstall the correct one (see below).

Installation (only if RTK not available or wrong RTK installed)

Step 0: Uninstall Wrong RTK (if needed)

If you accidentally installed Rust Type Kit:

```bash
cargo uninstall rtk
```

Quick Install (Linux/macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
```

After installation, verify you have the correct rtk:

```bash
rtk gain  # Must show token savings stats (not "command not found")
```

Alternative: Manual Installation

```bash
# From rtk-ai repository (NOT reachingforthejack!)
cargo install --git https://github.com/rtk-ai/rtk

# OR (if published and correct on crates.io)
cargo install rtk

# ALWAYS VERIFY after installation
rtk gain  # MUST show token savings, not "command not found"
```

⚠️ WARNING: `cargo install rtk` from crates.io might install the wrong package. Always verify with `rtk gain`.

Project Initialization

Which mode to choose? Do you want RTK active across ALL Claude Code projects?

  ├─ YES → `rtk init -g` (recommended)
  ├─ YES, minimal → `rtk init -g --hook-only`
  └─ NO, single project → `rtk init`

Recommended: Global Hook-First Setup

```bash
rtk init -g
```

# Automated alternatives:
`rtk init -g --auto-patch`  # Patch without prompting
`rtk init -g --no-patch`    # Print manual instructions instead

Verify installation

```bash
rtk init --show  # Check hook is installed and executable
```

Token savings: ~99.5% reduction (example)

Upgrading from Previous Version

From old 137-line CLAUDE.md injection (pre-0.22):

```bash
rtk init -g  # Automatically migrates to hook-first mode
```

Troubleshooting and common commands are included in the project's README.
