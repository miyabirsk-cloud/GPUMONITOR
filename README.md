# GPU Monitor

A lightweight Linux desktop monitor for AMD GPUs using the kernel's AMDGPU
sysfs sensors. It shows live GPU and VRAM usage, temperature, board power, fan
speed, and four history graphs, with dark and light themes.

## Install

On a Linux system with Python 3.10 or newer:

```bash
git clone https://github.com/miyabirsk-cloud/GPUMONITOR.git
cd GPUMONITOR
./install.sh
```

The installer puts the app and its Python environment in
`~/.local/share/gpu-monitor`, adds a **GPU Monitor** desktop/app-menu entry,
and creates the `gpu-monitor` command in `~/.local/bin`. It uses an existing
system PySide6 installation if available; otherwise it installs PySide6 into
the app's virtual environment.

If Python virtual-environment support is not installed on your distribution,
install its `venv`/`python-venv` package first. Internet access is needed only
when PySide6 is not already available to Python.

## Run from source

```bash
python3 -m pip install .
gpu-monitor
```

## Hardware support

The monitor currently supports AMD GPUs exposed by the Linux `amdgpu` driver.
Sensor availability depends on the GPU and driver; fan readings are shown when
the card exposes a fan sensor. The app reads sensors without root privileges
and does not change fan controls.
