U.S. Civic Contact Finder — Run & Distribution

Overview

This repository contains the original Flask web app (civic_contact_finder/) and native launchers/packaging that run the web app locally and present a desktop experience. The launcher starts the Flask backend on localhost and opens the UI in a browser or embedded WebView2 window.

1) Developer (run from source)

Requirements
- Python 3.10+ (for running the Flask app)
- dotnet SDK (for building the cross-platform launcher and WPF app)

Quick steps (Windows)
- Open a developer PowerShell in the repository root
- cd "civic_contact_finder"
- python -m venv .venv
- .\.venv\Scripts\Activate.ps1
- pip install -r requirements.txt
- python app.py
- Open http://127.0.0.1:5001/ in your browser

Quick steps (macOS / Linux)
- cd civic_contact_finder
- python3 -m venv .venv
- source .venv/bin/activate
- pip install -r requirements.txt
- python3 app.py
- Open http://127.0.0.1:5001/

Note: "dotnet run" is only used for building or running the .NET launcher or WPF app during development. The published Windows desktop executable (CivicContactFinderDesktop.exe or CivicContactFinderLauncher.exe) is a self-contained executable produced by dotnet publish and does not require dotnet to be installed by end users.

2) Packaged distributions (recommended)

What the packages include
- A single-file launcher executable (platform-specific)
- The Flask web app files (civic_contact_finder/)
- A bundled portable Python virtual environment (so users do not need to install Python)
- Helper scripts and the WebView2 Evergreen bootstrapper (Windows ZIP)

Windows (ZIP / Installer)
- Unzip the provided release ZIP.
- Run CivicContactFinderLauncher.exe to start the bundled backend and open the UI in the default browser.
- For a single-window native UI, use CivicContactFinderDesktop.exe (WPF + WebView2). WebView2 runtime is required. The ZIP includes the Evergreen bootstrapper so installers can install the runtime if missing.

Linux (AppImage)
- Make the file executable: chmod +x CivicContactFinderLauncher.AppImage
- Run it: ./CivicContactFinderLauncher.AppImage
- The AppImage bundles a portable Python venv and the launcher; it will start the backend and open the system browser.

macOS (.pkg)
- Run the installer from the release; a bundled Python runtime is installed with the app.
- Note: macOS packages in releases are unsigned by default and Gatekeeper will warn you.

3) How the launcher & embedded Python work

- The launcher looks for a bundled portable Python venv included with the distribution. If present, it uses that Python to run app.py. If not found, it will try any .venv in the repo or the system Python.
- The launcher performs a simple health-check (HTTP /healthz) and waits until the Flask server is ready before opening the UI.
- Because the Python runtime is bundled inside the distribution, end users typically do not need to install Python.

4) WebView2 (Windows desktop)

- The WPF desktop app (CivicContactFinderDesktop) uses Microsoft WebView2 for an embedded browser control.
- WebView2 requires the WebView2 runtime (Evergreen or fixed). The Windows ZIP includes the Evergreen bootstrapper; installers can run it to ensure the runtime is present.
- If WebView2 is missing, the launcher falls back to opening the UI in the default browser.

7) Troubleshooting

- If the UI does not open: check the launcher console for errors and verify the server is reachable at http://127.0.0.1:5001/.
- If WebView2 fails to initialize on Windows: run the Evergreen bootstrapper included in the ZIP, or allow the launcher to open the UI in your default browser.
- On Linux, ensure the AppImage/executable has the execute bit (chmod +x).

Support & Sources
- Developer docs, API details, and tests live inside civic_contact_finder/ — see civic_contact_finder/README.md for backend specifics.