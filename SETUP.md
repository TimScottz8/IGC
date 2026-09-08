# New machine setup for Gaggles

This project is a Python desktop app for analysing glider contest traces. It uses a local virtual environment and Qt-based UI libraries.

## 1. Install the base toolchain

If VS Code is already installed, make sure the following are available on the new computer:

- Git
- Python 3.11 or 3.12 (preferred: 3.12)
- A terminal with access to `python`, `pip`, and `venv`

## 2. Install VS Code Python tooling

Open VS Code and install:

- Python
- Pylance
- Python Test Explorer (optional but useful)

Then open the project folder in VS Code.

## 3. Clone the repository

```bash
git clone https://github.com/TimScottz8/IGC.git
cd IGC
```

## 4. Create a virtual environment

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

## 5. Install the project runtime libraries

This project depends on Qt, geospatial/IGC parsing, and data-analysis packages.

Install the key runtime stack:

```bash
pip install PySide6 pyqtgraph pyproj libigc requests beautifulsoup4 pandas plotly numpy scipy pytest
```

If you want a few extra utilities for future scripting or debugging, you can also add:

```bash
pip install matplotlib tqdm
```

## 6. Linux-specific GUI dependencies

On Ubuntu or Debian-based systems, the Qt app may need a few system packages available at runtime:

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0
```

If the machine is headless or running in CI, tests can be executed with:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

## 7. Run the app

From the project root:

```bash
.venv/bin/python qt_app.py
```

## 8. Run the tests

The current regression checks are:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q test_geo_task.py
.venv/bin/python -m pytest -q test_gaggle_analysis.py
```

## 9. Typical developer workflow

```bash
source .venv/bin/activate
python qt_app.py
```

When working in VS Code, set the interpreter to the project-local `.venv` so editor diagnostics and test discovery match the environment used by the app.

## Notes

- This project is intentionally focused on a local desktop workflow rather than a web deployment.
- The repo is analysis-first, so the main goal is to keep the Qt viewer, timing state, and gaggle logic working while expanding the analysis features.
- The project documentation in `README.md`, `Pathway.md`, and `Progress.md` describes the intended direction and current status.
