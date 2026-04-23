#!/usr/bin/env node
/* Turing launcher — bootstraps the Python package into an isolated venv on
 * first run, then proxies the CLI.
 *
 * The venv lives at:
 *   ~/.cortex-protocol/npm-venv   (POSIX)
 *   %LOCALAPPDATA%/cortex-protocol/npm-venv   (Windows)
 *
 * We do not try to reinvent pip — we delegate to `python -m pip install`
 * against a pinned version that matches this npm package.
 */

"use strict";

const { spawnSync, spawn } = require("node:child_process");
const { existsSync, mkdirSync } = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const PKG_VERSION = require("../package.json").version;
const PY_PKG = `cortex-protocol==${PKG_VERSION}`;

const isWin = process.platform === "win32";

function venvRoot() {
  if (isWin) {
    const base = process.env.LOCALAPPDATA
      || path.join(os.homedir(), "AppData", "Local");
    return path.join(base, "cortex-protocol", "npm-venv");
  }
  return path.join(os.homedir(), ".cortex-protocol", "npm-venv");
}

function venvBin(name) {
  const root = venvRoot();
  if (isWin) {
    return path.join(root, "Scripts", `${name}.exe`);
  }
  return path.join(root, "bin", name);
}

function findPython() {
  // Prefer the freshest Python ≥3.10 we can find. macOS often has only
  // `python3`; Windows often has `py -3`.
  const candidates = isWin
    ? ["py", "python3", "python"]
    : ["python3.12", "python3.11", "python3.10", "python3", "python"];
  for (const name of candidates) {
    const args = name === "py" ? ["-3", "-c", "import sys;print(sys.version_info[:2])"] : ["-c", "import sys;print(sys.version_info[:2])"];
    const probe = spawnSync(name, args, { encoding: "utf8" });
    if (probe.status === 0) {
      return name;
    }
  }
  return null;
}

function bootstrap() {
  const root = venvRoot();
  if (existsSync(venvBin("cortex-protocol"))) {
    return;  // already set up
  }

  const python = findPython();
  if (!python) {
    console.error(
      "Turing requires Python 3.10+ on PATH. Install Python and re-run.\n" +
      "See https://www.python.org/downloads/."
    );
    process.exit(1);
  }

  console.error("Turing: bootstrapping Python venv (first run only)...");
  mkdirSync(root, { recursive: true });

  const venvCmd = python === "py"
    ? ["py", ["-3", "-m", "venv", root]]
    : [python, ["-m", "venv", root]];
  let r = spawnSync(venvCmd[0], venvCmd[1], { stdio: "inherit" });
  if (r.status !== 0) {
    console.error("Turing: failed to create venv.");
    process.exit(r.status || 1);
  }

  const venvPython = isWin
    ? path.join(root, "Scripts", "python.exe")
    : path.join(root, "bin", "python");

  r = spawnSync(venvPython,
    ["-m", "pip", "install", "--quiet", "--upgrade", "pip"],
    { stdio: "inherit" });
  if (r.status !== 0) {
    process.exit(r.status || 1);
  }

  r = spawnSync(venvPython,
    ["-m", "pip", "install", "--quiet", PY_PKG],
    { stdio: "inherit" });
  if (r.status !== 0) {
    console.error(`Turing: failed to install ${PY_PKG}.`);
    process.exit(r.status || 1);
  }
  console.error("Turing: ready.");
}

function main() {
  bootstrap();
  const exe = venvBin("cortex-protocol");
  const child = spawn(exe, process.argv.slice(2), {
    stdio: "inherit",
    env: process.env,
    windowsHide: false,
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });
}

main();
