# Windows Build And Packaging

This project ships a PyInstaller bundle and wraps it in a WiX MSI.

## Recommended Debug Sequence

1. Run from IDE/CLI.
2. Build and run PyInstaller `onedir`.
3. Validate `onedir` on a clean Windows environment.
4. Build and run PyInstaller `onefile`.
5. Build MSI with WiX.
6. Validate MSI and run installer smoke test.

This order reduces the search space. Most packaging issues are already present in the
PyInstaller output before WiX is involved.

## Local Commands

```powershell
pip install . "pyinstaller==6.19.0"
pip install "git+https://github.com/synarius-project/synarius-apps.git" --no-deps

# onedir diagnostic build
pyinstaller --noconfirm --clean synarius_studio_onedir.spec
dist\synarius-studio\synarius-studio.exe --smoke-exit

# onefile release-like build
pyinstaller --noconfirm --clean synarius_studio.spec
dist\synarius-studio.exe --smoke-exit
```

## Logging Location

Application logs are written early during startup to a per-user log directory from
`platformdirs` (fallback: `%LOCALAPPDATA%` on Windows), file:

- `synarius-studio.log`

## CI Diagnostics

- `release.yml` uploads PyInstaller `warn-*.txt` and `xref-*.html`.
- `pyinstaller-smoke.yml` runs on PR/workflow_dispatch and builds `onedir` for easier inspection.

