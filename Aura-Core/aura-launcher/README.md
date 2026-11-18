# Aura Launcher

Native Windows shell for Aura. One double-click brings Aura's full stack up,
shows status in the system tray, and never opens a terminal.

This crate is **independent of `aura-app/`** by design (see V1PRD §3.7). It
spawns SurrealDB and the Python AI Engine as native OS child processes with
visible terminal windows — no Docker, no containers, no black boxes.

## Stack

- Tauri 2.x (Rust + WebView2)
- Tray-only app, no primary window
- Spawns `surreal` and `uvicorn` as native child processes
- Probes `/health` endpoints via HTTP

## Prerequisites (Windows)

1. **Rust** with the MSVC toolchain (`stable-x86_64-pc-windows-msvc`).
2. **Visual Studio 2019/2022 BuildTools** with the **Desktop development with C++** workload.
3. **Windows 10 or 11 SDK** — install via the VS Installer ("Individual components" → any
   `Windows 11 SDK (10.0.22621.0)` or `Windows 10 SDK 10.0.x.0`). Without this you'll see
   `LNK1181: cannot open input file 'kernel32.lib'` even at `cargo check` time.
4. **SurrealDB CLI** (`surreal`) on PATH — [install via scoop/brew/msi](https://surrealdb.com/install).
5. **Python 3.12+** with `uvicorn` and the Aura backend dependencies installed.

Cargo must be invoked from a Developer Command Prompt or with `vcvars64.bat` sourced —
the bash `link.exe` from Git's `/usr/bin` shadows MSVC's linker on PATH otherwise.

## Build

```powershell
# Generate placeholder icons (run once, or whenever you tweak the script)
py scripts\generate_placeholder_icons.py

# Dev build (from a Developer Command Prompt, or via vcvars64)
cd src-tauri
cargo check
cargo build

# Release
cargo build --release
```

The release binary lands at `src-tauri/target/release/aura-launcher.exe`.

If running cargo from outside a Dev Prompt, wrap the call:

```powershell
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" && cd /d <repo>\Aura-Core\aura-launcher\src-tauri && cargo check'
```

## Configure

Drop a copy of `aura.config.toml.example` next to the .exe and rename it to
`aura.config.toml`. Edit `aura_app_path` to point at your `aura-app/` checkout.
The launcher reads this on every boot — no rebuild needed when you tweak
ports or service names.

## State machine

```
Idle → ServicesStarting → ServicesUp → HealthChecking → Ready
                                        ↓
                                     Stopping → Stopped
                                        ↓
                                      Failed
```

Tray icon color tracks state: grey (stopped/idle), amber (transitioning),
blue glow (ready), red (failed).

## Tray menu

- ● *current state*  (status row, disabled)
- Open Mission Control / Open IDE / Open Logs
- Restart Backend Only / Restart All / Start Aura / Stop Aura
- Edit .env…
- Quit Launcher

## Sealed paths

Per V1PRD §5.5, Aura's self-evolution engine **must never** write into
`aura-launcher/`. The launcher's deny-listing on the Aura side is enforced in
`src/aura/tools/filesystem.py`; this crate is just the consumer of that
guarantee.
