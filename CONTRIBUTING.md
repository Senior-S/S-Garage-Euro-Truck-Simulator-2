# Development and contributions

For the ready-to-run app, use the **[Windows download](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/releases)** and **[installation guide](docs/INSTALLATION.md)**. The steps below are for developers.

## Run from source

Use Windows x64, Python 3.10 or newer, and Node.js 20 or newer. Download this repository with **Code → Download ZIP**, then extract it, or clone it with Git.

Double-click **Start Garage.cmd**. It installs Python dependencies, builds the UI when necessary, downloads checksum-verified conversion tools, and opens the local garage. **Stop Garage.cmd** stops this source launcher's server. Internet access is needed for that initial setup.

For separate development terminals:

```powershell
python -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File setup-tools.ps1
python backend/server.py
```

```powershell
cd ui
npm ci
npm run dev
```

Vite proxies API and asset requests to the server on port 8765. `npm run build` generates the production UI. The Python server binds to loopback.

## Verify changes

```powershell
python -m unittest discover -s tests
cd ui
node --test tests/scene-update.test.js
npm run build
```

Save-writing tests use temporary fixtures. Do not add real saves, extracted game assets, personal settings, or access tokens to the repository. For rendering changes, compare the affected part in both ETS2 and the garage.

## Build the Windows download

On Windows with Python 3.13 and Node.js 22:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File build-release.ps1
```

The script builds the frontend, packages Python and the conversion tools with PyInstaller, includes docs and third-party notices, downloads matching tool source archives, and writes release files to `release/`. `dist/S Garage/S Garage.exe --check` verifies the packaged UI and tools; the result is logged to `%LOCALAPPDATA%\ETS2Garage\package-check.json`.

GitHub Actions runs the tests, builds the Windows package, and uploads a downloadable build artifact. User-facing downloads are published separately under **Releases**.

Before publishing a release, validate the EXE on Windows, inspect the ZIP for private/game data, and upload the app ZIP, matching tool source archives, and `SHA256SUMS.txt` together. Label early builds clearly as previews.

## Report or contribute

Use the **[issue forms](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/issues/new/choose)** for bugs and ideas. Small, focused pull requests are easier to review. Explain the changed behavior and how you verified it.

Contributions to the original project code are submitted under its **[PolyForm Noncommercial license](LICENSE)**. Keep third-party license notices intact. Contact **`seniors` on Discord** for questions.
