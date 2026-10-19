# U.S. Civic Contact Finder — Developer Guide

## Overview

This repository contains the original Flask web app in `civic_contact_finder/` and native launchers/packaging that run the web app locally and present a desktop experience. The launcher starts the Flask backend on localhost and opens the UI in a browser or embedded WebView2 window.

## Run from source

### Requirements

- Python 3.10+
- .NET SDK for building the desktop launcher and Windows WPF app

### Quick steps (Windows)

```powershell
cd "civic_contact_finder"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5001/ in your browser.

### Quick steps (macOS / Linux)

```bash
cd civic_contact_finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Then open http://127.0.0.1:5001/.

## Packaged distributions

### What the packages include

- a launcher executable for the current platform
- the Flask app files under `civic_contact_finder/`
- a bundled Python environment when needed
- helper scripts and Windows WebView2 bootstrap support

### Windows

- Unzip the published release ZIP.
- Run the bundled launcher or desktop app.
- The Windows desktop shell can use WebView2 for an embedded browser; if the runtime is missing, it can fall back to the default browser.

### Linux

- Use the Linux package produced in `publish/`.
- Make the file executable if needed and launch it.

### macOS

- Use the signed or unsigned package from the release pipeline or a macOS build machine.

## Launcher behavior

- The launcher checks for a bundled Python runtime when present.
- It starts the Flask backend and waits for the health endpoint before opening the UI.
- End users usually do not need to install Python manually for packaged builds.

## WebView2 (Windows desktop)

- The WPF desktop app uses Microsoft WebView2 for an embedded browser control.
- WebView2 may need the evergreen runtime installed.
- If missing, the app can open in the default browser instead.

## Troubleshooting

- If the app does not open, check the console for launcher errors.
- Verify the backend is reachable at http://127.0.0.1:5001/.
- On Linux, ensure the package/executable has execute permission.

## Support and sources

- Core app logic lives in `civic_contact_finder/app.py`
- Backend data and app assets live under `civic_contact_finder/`
- Packaging scripts and launchers live under `tooling/`, `CivicContactFinderLauncher/`, and `CivicContactFinderDesktop/`
