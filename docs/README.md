# U.S. Civic Contact Finder — static demo

This folder contains a static version of the Civic Contact Finder. It uses only HTML, CSS, JavaScript, and the CSV directories in `civic_contact_finder/data/`; it does not run Flask or require Python packages.

## Run locally

From the repository root, start a local static-file server:

```powershell
python -m http.server 8000 --directory Demo
```

Then open <http://localhost:8000/>. Opening `index.html` directly as a `file://` URL is not supported because browsers block the CSV fetches.

The demo loads its directory from the included CSV files and starts with Washington, D.C. selected. Search happens in your browser. The static version does not geocode locations or fetch live FDA recall notices; it links to the official recall sources instead.

## GitHub Pages

When the repository is published from its root, this page is available at `/Demo/`. Its assets and directory paths are relative, so they also work when the folder is published as the site root. To publish this folder at the site root through GitHub Actions, configure the Pages workflow to upload the contents of `Demo/` as the deployment artifact.

The Python files under `civic_contact_finder/` are not used by this static page.
