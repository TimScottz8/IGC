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

> The VS Code Python extension will normally detect the local `.venv` automatically when it is created inside the workspace. If it does not, use the command `Python: Select Interpreter` and choose the environment in this repo.

## 3. Clone the repository

```bash
git clone https://github.com/TimScottz8/IGC.git
cd IGC
```

## 4. Create a virtual environment

From the project root:

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

### Windows (Command Prompt)

```cmd
py -m venv .venv
.venv\Scripts\activate.bat
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

## 6. OS-specific GUI dependencies

### Linux / Ubuntu / Debian

The Qt app may need a few system packages available at runtime:

```bash
sudo apt-get update
sudo apt-get install -y libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0
```

### Windows

Windows typically works with the Python packages above, but the local Python environment still needs the Windows runtime pieces used by Qt. If the app fails to launch, ensure the system has the usual Visual C++ runtime installed and re-open VS Code after creating the venv.

If the machine is headless or running in CI, tests can be executed with:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

On Windows, use the local venv interpreter directly instead of the Linux-specific path:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 7. Run the app

### Linux/macOS

```bash
.venv/bin/python qt_app.py
```

### Windows

```powershell
.\.venv\Scripts\python.exe qt_app.py
```

## 8. Run the tests

The current regression checks are:

### Linux/macOS

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q test_geo_task.py
.venv/bin/python -m pytest -q test_gaggle_analysis.py
```

### Windows

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_geo_task.py
.\.venv\Scripts\python.exe -m pytest -q test_gaggle_analysis.py
```

## 9. Typical developer workflow

### Linux/macOS

```bash
source .venv/bin/activate
python qt_app.py
```

### Windows

```powershell
.\.venv\Scripts\Activate.ps1
python qt_app.py
```

When working in VS Code, set the interpreter to the project-local `.venv` so editor diagnostics and test discovery match the environment used by the app. If Copilot is not picking up the environment, use the `Python: Select Interpreter` command and choose the project venv.

## Notes

- This project is intentionally focused on a local desktop workflow rather than a web deployment.
- The repo is analysis-first, so the main goal is to keep the Qt viewer, timing state, and gaggle logic working while expanding the analysis features.
- The project documentation in `README.md`, `Pathway.md`, and `Progress.md` describes the intended direction and current status.
