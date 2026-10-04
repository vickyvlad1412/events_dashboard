import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import APP_NAME, APP_VERSION
from app.db import write_catalog_seed

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
EXE_NAME = "WatchDashboard"
ICON = ROOT / "assets" / "app.ico"
INSTALLER_SCRIPT = ROOT / "installer" / "WatchDashboard.iss"
SOURCE_DB = ROOT / "data" / "dashboard.db"
SEED_DB = BUILD_DIR / "seed" / "catalog_seed.db"
ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def _data(source: Path, target: str) -> list[str]:
    return ["--add-data", f"{source}{os.pathsep}{target}"]


def _find_iscc() -> Path | None:
    found = shutil.which("iscc")
    if found:
        return Path(found)
    return next((path for path in ISCC_CANDIDATES if path.exists()), None)


def _build_installer(app_dir: Path) -> Path | None:
    iscc = _find_iscc()
    if not iscc:
        print("\nInno Setup 6 isn't installed, so no installer was made.")
        print("Install it from https://jrsoftware.org/isdl.php and run this script again.")
        return None
    result = subprocess.run(
        [
            str(iscc),
            f"/DAppVersion={APP_VERSION}",
            f"/DSourceDir={app_dir}",
            f"/DOutputDir={DIST_DIR}",
            str(INSTALLER_SCRIPT),
        ],
        cwd=INSTALLER_SCRIPT.parent,
    )
    if result.returncode != 0:
        return None
    setup = DIST_DIR / f"WatchDashboard-Setup-{APP_VERSION}.exe"
    archive = shutil.make_archive(str(setup.with_suffix("")), "zip", root_dir=DIST_DIR, base_dir=setup.name)
    return Path(archive)


def main() -> int:
    env_file = ROOT / ".env"
    if not env_file.exists():
        print("No .env found. The build needs your API keys in .env.")
        return 1

    if SOURCE_DB.exists():
        count = write_catalog_seed(SOURCE_DB, SEED_DB)
        print(f"Catalog seed: {count} teams and players from {SOURCE_DB}")
    else:
        print(f"No {SOURCE_DB}; building without a catalog seed.")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", EXE_NAME,
        "--icon", str(ICON),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "pyinstaller"),
        "--specpath", str(BUILD_DIR),
        *_data(ROOT / "app" / "templates", "app/templates"),
        *_data(ROOT / "app" / "static", "app/static"),
        *_data(ROOT / "app" / "models" / "schema.sql", "app/models"),
        *_data(env_file, "."),
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "apscheduler",
        "--copy-metadata", "apscheduler",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.winforms",
    ]
    if SEED_DB.exists():
        args += _data(SEED_DB, "seed")
    args.append(str(ROOT / "desktop.py"))

    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    app_dir = DIST_DIR / EXE_NAME
    installer_zip = _build_installer(app_dir)
    print(f"\n{APP_NAME} {APP_VERSION} built:")
    print(f"  App folder: {app_dir}")
    print(f"  Run:        {app_dir / (EXE_NAME + '.exe')}")
    if installer_zip:
        print(f"  Send this:  {installer_zip}")
    return 0 if installer_zip else 2


if __name__ == "__main__":
    sys.exit(main())
