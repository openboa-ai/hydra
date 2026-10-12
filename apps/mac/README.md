# Hydra for macOS

A Tauri 2 application with a TypeScript operations window and a Rust-owned menu
bar. It calls the installed Python control core with isolated, fixed arguments.
It does not install a daemon, start native Codex turns or change external schedules.

Start and Resume allow new eligible Hydra work. Pause and Stop close the shared
admission gate. Execution termination is a separate observation. Unknown ownership
and unverified schedule coverage remain visible and can hold Stop and Quit.
Closing the window hides it; the menu bar can reopen it.

## Build and verification

Use the host's approved build/storage runner for these commands, with this
directory as the working directory:

```sh
npm ci
npm run typecheck
npm test
npm run verify:theme
npm run build
npm run tauri -- build --bundles app
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

The packaged app must be launched with two explicit absolute paths:

```sh
Hydra.app/Contents/MacOS/hydra-operations --runtime /absolute/installed/bin/python3 --config /absolute/host.toml
```

The Python environment must contain the reviewed Hydra installation. The bridge
uses `-I`, a trusted working directory and a controlled environment; project
modules, `PYTHONPATH` and user site-packages do not select its implementation.
Do not use an active product configuration for development fixtures.

The renderer has no generic shell, filesystem, window-creation or URL-opening
permission. Only the main local window can invoke status, scoped control,
validated record opening and Stop and Quit. GitHub text is rendered as text.

## Theme

`src/theme-map.json` records the canonical token names, complete alias chains,
resolved values and source content digest. `src/tokens.css` contains the exact
CSS values. To independently compare the mapping with the original token file:

```sh
node scripts/theme.mjs --check /absolute/canonical/openboa.tokens.json
```

The original Martian Grotesk and Pretendard Variable font files and their OFL
licenses are bundled locally. Theme choice is in-memory and follows the system
by default. State always includes words and a symbol, and static cards have no
shadows.

Source checks and isolated app fixtures do not establish installed runtime
coverage or production-native control. Record those qualifications separately.
