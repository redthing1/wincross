# wincross

build windows targets on linux using a dockerized msvc+wine toolchain.

## what

- a small cli to configure/build/test inside a container
- project settings live in a `wincross.toml` file
- machine settings live in `.wincross/build_config.json`

## quick start

```bash
tools/wincross/bin/wincross init --toolchain tool=/path/to/toolchain:/opt/tool:ro
tools/wincross/bin/wincross configure
tools/wincross/bin/wincross build
tools/wincross/bin/wincross test
```

## config

project config (`wincross.toml`):
- defaults for cmake, toolchains, env, vcpkg
- supports placeholders like `{state_dir}`, `{build_dir}`, `{config_dir}`

machine config (`.wincross/build_config.json`):
- host paths, mounts, and local cache locations

## overrides

- `--project-config /path/to/wincross.toml`
- `WINCROSS_PROJECT_CONFIG=/path/to/wincross.toml`
- `--root /path/to/project`
- `WINCROSS_ROOT=/path/to/project`
