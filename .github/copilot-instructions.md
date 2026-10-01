# Copilot instructions for this repository

This repo is a Python desktop application for analysing glider contest traces. Use the local project environment for any work on this codebase.

## Environment and interpreter

- Always prefer the repo-local virtual environment over the system Python.
- Detect the current OS automatically:
  - Linux/macOS: use `.venv/bin/python` and `.venv/bin/pytest`
  - Windows: use `.venv\Scripts\python.exe` and `.venv\Scripts\python.exe -m pytest`
- If the workspace does not already have a `.venv`, create one before running code or tests.
- When the Python extension asks for an interpreter, select the project-local `.venv` in this workspace.
- If a local environment is not selected, mention this and ask the user to select the repo venv before continuing.

## Project commands

Use the repo-local Python interpreter for any validation or execution, for example:

- Linux/macOS:
  - `.venv/bin/python qt_app.py`
  - `.venv/bin/python -m pytest -q test_geo_task.py`
  - `.venv/bin/python -m pytest -q test_gaggle_analysis.py`
- Windows:
  - `.venv\Scripts\python.exe qt_app.py`
  - `.venv\Scripts\python.exe -m pytest -q test_geo_task.py`
  - `.venv\Scripts\python.exe -m pytest -q test_gaggle_analysis.py`

For headless / CI-style validation, prefer:

- Linux/macOS: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
- Windows: `.venv\Scripts\python.exe -m pytest -q`

## Repository context

- This project is analysis-first and multi-flight oriented.
- Key files to look at for architecture context:
  - `README.md`
  - `Pathway.md`
  - `Progress.md`
  - `qt_app.py`
  - `qt_viewer.py`
  - `gaggle_analysis.py`
  - `flight_loader.py`
- The app is Qt-based and should be treated as a desktop workflow rather than a web app.

## Working style

- Prefer small, focused edits tied to the root cause.
- Before claiming a fix works, run the relevant test or minimal validation command using the repo-local interpreter.
- Keep the project stable; this repo is currently focused on a working multi-flight viewer and thermal gaggle analysis.
- If a command is OS-specific, match it to the current machine automatically.

## Setup reminder

When the user asks to analyse the repo or investigate a bug, ensure the environment is ready first:

1. check whether `.venv` exists in the repo root
2. if it does not, create it using the OS-appropriate commands
3. select the local interpreter in VS Code
4. then run the relevant tests or app commands with the repo-local interpreter
