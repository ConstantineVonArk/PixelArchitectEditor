# SC3K Architecture Builder 1.2 — Windows build kit

**Author: Constantine von Ark**  
Copyright © 2026 Constantine von Ark. All rights reserved.

This repository contains the **English-language** Windows build source for
SC3K Architecture Builder, including the complete pixel-art sprite library,
roof and architectural palettes, and a GitHub Actions workflow that packages
a Windows executable.

## How to build on GitHub (no Windows computer needed)

1. Create a **new GitHub repository** (private is fine).
2. Upload **the contents of this ZIP**, not the ZIP itself, to the repository
   root. Include the hidden **`.github/workflows/windows-build.yml`** file.
   GitHub's **Add file → Upload files** supports folder uploads; if your upload
   method strips the hidden `.github` folder, create that path manually.
3. Commit the files to the repository's `main` branch.
4. Open **Actions → Build SC3K Architecture Builder for Windows**.
5. If it has not started automatically, click **Run workflow → Run workflow**.
6. Wait for the green completed run; click the run and find **Artifacts**.
7. Download **SC3K-Architecture-Builder-Windows**. GitHub downloads it as a ZIP.
8. On Windows, extract it and double-click **SC3K Architecture Builder.exe**.

The EXE is produced **on GitHub's Windows runner**. It is not included in this
source ZIP. The app is bundled in **one-folder mode**; keep `_internal` with
its EXE. The workflow does not require any paid Windows licence or signing key,
but normal GitHub Actions account/repository limits apply.

### Troubleshooting

- **No Actions tab?** Check repository Actions settings and workflow visibility.
- **No build run?** Verify that `.github/workflows/windows-build.yml` was uploaded.
- **Missing images?** Verify that the top-level `library/` folder was uploaded.
- **EXE does not start?** Extract the artifact ZIP first, keep the folder intact,
  and inspect the Actions run logs. This is an unsigned executable.
- **Legacy macOS volume project?** Russian roof labels in older JSON volume
  files are converted automatically on import.

### Source files

- `facade_builder.py`: English 3-tab application entry point.
- `volume_editor.py`: building volume, roofs and shadow renderer.
- `library/`: ISO/FRONT window art, wall assets and two palettes.
- `.github/workflows/windows-build.yml`: automated Windows packaging.
- `requirements.txt`: dependencies for local running or packaging.

### Running the Python source locally

```bash
python -m pip install -r requirements.txt
python facade_builder.py
```

### Author and rights

**Constantine von Ark** — original author and creator.  
Copyright © 2026 Constantine von Ark. All rights reserved.

No redistribution or modification licence is granted by this README.
