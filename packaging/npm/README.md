# Turing (cortex-protocol) — npm launcher

This package is a thin launcher around the real Python distribution
(`cortex-protocol` on PyPI). It exists so you can run Turing with a
one-liner from any Node toolchain:

```sh
npx cortex-protocol@latest init agent.yaml
```

On first run it creates a dedicated Python venv under:
- `~/.cortex-protocol/npm-venv` on macOS/Linux
- `%LOCALAPPDATA%\cortex-protocol\npm-venv` on Windows

and installs the matching Python release into it. Subsequent runs proxy
arguments straight through without the bootstrap cost.

Requires Python 3.10+ on `PATH`.

To upgrade: `npm install -g cortex-protocol@<newer>` bumps the version,
and the next invocation reinstalls into the venv.
