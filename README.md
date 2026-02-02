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
tools/wincross/bin/wincross shell
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

## extra args

for option-heavy commands, `--*-args` accepts a single string that is shell-split:

```bash
tools/wincross/bin/wincross configure --cmake-args "-S /work/project/samples/demo -B /work/project/.wincross/build-demo"
tools/wincross/bin/wincross build --build-dir /work/project/.wincross/build-demo
tools/wincross/bin/wincross test --test-dir /work/project/.wincross/build-demo
```
