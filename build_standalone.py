"""
Yaw-Yaw Standalone Installer & Portable Package Builder
------------------------------------------------------
Builds:
1. dist/Yaw-Yaw (Fully self-contained portable folder with zero dependencies)
2. dist/Yaw-Yaw-Setup-v2.0.exe (Single-file Windows Setup Wizard installer)
3. dist/Yaw-Yaw-Portable-v2.0.zip (Portable zip package)
"""
import os
import sys
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_DIR = DIST / "Yaw-Yaw"
ISCC_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"
if not ISCC_PATH.is_file():
    ISCC_PATH = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")


def log(msg):
    print(f"==> {msg}", flush=True)


def step1_ensure_icon():
    log("Checking/generating application icon...")
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(exist_ok=True)
    ico_file = assets_dir / "yaw_yaw.ico"
    if ico_file.is_file():
        log("Icon already exists.")
        return ico_file

    from PIL import Image, ImageDraw
    sizes = [256, 128, 64, 48, 32, 16]
    images = []
    for s in sizes:
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pad = int(s * 0.06)
        r = int(s * 0.22)
        draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r, fill=(25, 46, 49, 255))
        border_w = max(1, int(s * 0.03))
        draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=r, outline=(13, 148, 136, 255), width=border_w)
        cx, cy = s / 2.0, s / 2.0
        bar_w = max(2, int(s * 0.08))
        spacing = int(s * 0.12)
        heights = [0.22, 0.38, 0.54, 0.38, 0.22]
        colors = [(94, 234, 212), (45, 212, 191), (20, 184, 166), (45, 212, 191), (94, 234, 212)]
        start_x = cx - (len(heights) - 1) * spacing / 2.0
        for i, h_pct in enumerate(heights):
            bx = start_x + i * spacing
            bh = s * h_pct
            y0, y1 = cy - bh / 2.0, cy + bh / 2.0
            draw.rounded_rectangle([bx - bar_w / 2, y0, bx + bar_w / 2, y1], radius=max(1, bar_w // 2), fill=colors[i] + (255,))
        images.append(img)
    images[0].save(str(ico_file), format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    log(f"Generated {ico_file}")
    return ico_file


def step2_compile_launcher():
    log("Compiling native Yaw-Yaw.exe launcher...")
    cs_file = ROOT / "launcher.cs"
    csc = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
    if not csc.is_file():
        raise RuntimeError("Microsoft .NET csc.exe compiler not found.")

    out_exe = ROOT / "Yaw-Yaw.exe"
    cmd = [
        str(csc),
        "/target:winexe",
        f"/win32icon:{ROOT / 'assets' / 'yaw_yaw.ico'}",
        f"/out:{out_exe}",
        str(cs_file)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to compile launcher: {res.stderr}")
    log(f"Native launcher compiled: {out_exe}")
    return out_exe


def step3_assemble_portable_payload():
    log("Assembling standalone payload in dist/Yaw-Yaw...")
    if APP_DIR.exists():
        log("Cleaning previous dist/Yaw-Yaw...")
        shutil.rmtree(APP_DIR)
    APP_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Copy core app files
    log("Copying app scripts and sources...")
    shutil.copy2(ROOT / "Yaw-Yaw.exe", APP_DIR / "Yaw-Yaw.exe")
    shutil.copy2(ROOT / "desktop_app.py", APP_DIR / "desktop_app.py")
    shutil.copy2(ROOT / "phase14_bootstrap.py", APP_DIR / "phase14_bootstrap.py")
    shutil.copy2(ROOT / "setup_local_languages.cmd", APP_DIR / "setup_local_languages.cmd")
    shutil.copy2(ROOT / "README.md", APP_DIR / "README.md")
    shutil.copy2(ROOT / "LICENSE", APP_DIR / "LICENSE")

    # Copy src
    shutil.copytree(ROOT / "src", APP_DIR / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Copy assets
    shutil.copytree(ROOT / "assets", APP_DIR / "assets")

    # Copy kokoro-data (models + voices)
    log("Copying Kokoro models and voice data...")
    shutil.copytree(
        ROOT / "kokoro-data",
        APP_DIR / "kokoro-data",
        ignore=shutil.ignore_patterns("*.wav", "*.jsonl", "hf-cache")
    )

    # 2. Build runtime
    runtime_dir = APP_DIR / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    base = Path(sys.base_prefix)
    log(f"Copying base Python runtime from {base}...")

    # Copy base python executables and dlls
    for item in base.iterdir():
        if item.is_file() and item.suffix.lower() in (".exe", ".dll", ".txt"):
            shutil.copy2(item, runtime_dir / item.name)

    # Copy DLLs
    log("Copying DLLs...")
    shutil.copytree(base / "DLLs", runtime_dir / "DLLs")

    # Copy tcl
    if (base / "tcl").is_dir():
        log("Copying tcl/tk files...")
        shutil.copytree(base / "tcl", runtime_dir / "tcl")

    # Copy Lib (standard library)
    log("Copying standard library...")
    shutil.copytree(
        base / "Lib",
        runtime_dir / "Lib",
        ignore=shutil.ignore_patterns("test", "tests", "idlelib", "site-packages", "__pycache__", "*.pyc")
    )

    # Copy site-packages from venv
    venv_sp = ROOT / "venv" / "Lib" / "site-packages"
    dest_sp = runtime_dir / "Lib" / "site-packages"
    log("Copying site-packages (PyTorch, Kokoro, audio libraries)...")

    def _ignore_sp(folder, names):
        ignored = set()
        p = Path(folder)
        is_sp_root = (p == venv_sp)
        for name in names:
            if name == "__pycache__" or name.endswith(".pyc"):
                ignored.add(name)
            elif is_sp_root and (
                name in ("pip", "wheel", "setuptools", "distutils", "_distutils_hack")
                or name == "distutils-precedence.pth"
                or name.startswith("pip-")
                or name.startswith("wheel-")
                or name.startswith("setuptools-")
            ):
                ignored.add(name)
        return ignored

    shutil.copytree(venv_sp, dest_sp, ignore=_ignore_sp)

    # Ensure kokoro/__init__.py in runtime has the None sys.stderr guard
    kokoro_init = dest_sp / "kokoro" / "__init__.py"
    if kokoro_init.is_file():
        k_content = kokoro_init.read_text(encoding="utf-8")
        if "if sys.stderr is not None:" not in k_content:
            k_content = k_content.replace("logger.add(", "if sys.stderr is not None:\n    logger.add(")
            kokoro_init.write_text(k_content, encoding="utf-8")

    # Add kokoro_local.pth in site-packages
    pth_file = dest_sp / "kokoro_local.pth"
    with open(pth_file, "w", encoding="utf-8") as f:
        f.write("..\\..\\..\\src\n")
        f.write("..\\..\\..\n")

    # 3. Add convenience launchers
    log("Creating helper batch and shortcut scripts...")

    # Yaw-Yaw.cmd (Console mode for debugging)
    cmd_launcher = APP_DIR / "Yaw-Yaw-Console.cmd"
    with open(cmd_launcher, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("cd /d \"%~dp0\"\n")
        f.write("set HF_HUB_OFFLINE=1\n")
        f.write("set TRANSFORMERS_OFFLINE=1\n")
        f.write("set HF_HUB_DISABLE_TELEMETRY=1\n")
        f.write("set DO_NOT_TRACK=1\n")
        f.write("set KOKORO_BASE_DIR=%~dp0kokoro-data\n")
        f.write("runtime\\python.exe desktop_app.py --offline %*\n")
        f.write("if errorlevel 1 pause\n")

    # Install-Shortcuts.cmd (creates desktop shortcut for portable users)
    install_shortcuts = APP_DIR / "Install-Shortcuts.cmd"
    with open(install_shortcuts, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("setlocal\n")
        f.write("cd /d \"%~dp0\"\n")
        f.write("powershell -NoProfile -ExecutionPolicy Bypass -Command \"$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\\Yaw-Yaw.lnk'); $s.TargetPath = '%~dp0Yaw-Yaw.exe'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0assets\\yaw_yaw.ico'; $s.Description = 'Yaw-Yaw Speech Studio'; $s.Save()\"\n")
        f.write("echo Desktop shortcut created.\n")
        f.write("pause\n")

    # Uninstall-Shortcuts.cmd
    uninstall_shortcuts = APP_DIR / "Uninstall-Shortcuts.cmd"
    with open(uninstall_shortcuts, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("del \"%USERPROFILE%\\Desktop\\Yaw-Yaw.lnk\" 2>nul\n")
        f.write("echo Desktop shortcut removed.\n")
        f.write("pause\n")

    log("Standalone payload created successfully!")


def step4_verify_portable_payload():
    log("Testing portable payload isolation and offline pipeline...")
    py_exe = APP_DIR / "runtime" / "python.exe"
    check_code = (
        "import sys, os; "
        "assert 'venv' not in sys.prefix, 'Leaking venv!'; "
        "import torch; "
        "import sounddevice; "
        "import soundfile; "
        "import pydub; "
        "import kokoro_tts_local; "
        "import desktop_app; "
        "from kokoro_tts_local import speech_service, mms_engine; "
        "p = speech_service.get_pipeline_for_voice('af_heart'); "
        "assert mms_engine.pack_status('tgl')['ready']; "
        "assert mms_engine.pack_status('ceb')['ready']; "
        "print('PASS: Isolated runtime & offline pipeline verified! Torch:', torch.__version__)"
    )
    res = subprocess.run(
        [str(py_exe), "-c", check_code],
        cwd=str(APP_DIR),
        capture_output=True,
        text=True
    )
    print(res.stdout.strip())
    if res.returncode != 0:
        print("STDERR:", res.stderr)
        raise RuntimeError("Portable payload failed self-test verification.")


def step5_generate_inno_script():
    log("Generating Inno Setup script (installer.iss)...")
    iss_content = f"""
; Inno Setup script for Yaw-Yaw Speech Studio
#define MyAppName "Yaw-Yaw"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Yaw-Yaw Studio"
#define MyAppExeName "Yaw-Yaw.exe"
#define MyAppSourceDir "{APP_DIR}"

[Setup]
AppId={{{{C49D6A9F-B374-4C3F-981F-8208A44917B2}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={DIST}
OutputBaseFilename=Yaw-Yaw-Setup-v2.0
SetupIconFile={ROOT / "assets" / "yaw_yaw.ico"}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"

[Files]
Source: "{{#MyAppSourceDir}}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\assets\\yaw_yaw.ico"
Name: "{{group}}\\Uninstall {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon; IconFilename: "{{app}}\\assets\\yaw_yaw.ico"

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "{{cm:LaunchProgram,{{#StringChange(MyAppName, '&', '&&')}}}}"; Flags: nowait postinstall skipifsilent
"""
    iss_file = ROOT / "installer.iss"
    with open(iss_file, "w", encoding="utf-8") as f:
        f.write(iss_content)
    log(f"Generated {iss_file}")
    return iss_file


def step6_compile_inno_installer(iss_file):
    if not ISCC_PATH.is_file():
        log(f"ISCC.exe not found at {ISCC_PATH}; skipping installer compilation.")
        return None

    log(f"Compiling installer with Inno Setup ({ISCC_PATH})...")
    res = subprocess.run([str(ISCC_PATH), str(iss_file)], capture_output=True, text=True)
    if res.returncode != 0:
        print("ISCC Output:", res.stdout)
        print("ISCC Errors:", res.stderr)
        raise RuntimeError("Inno Setup compilation failed.")
    
    setup_exe = DIST / "Yaw-Yaw-Setup-v2.0.exe"
    size_mb = setup_exe.stat().st_size / (1024 * 1024)
    log(f"SUCCESS: Installer created -> {setup_exe} ({size_mb:.1f} MB)")
    return setup_exe


def step7_create_portable_zip():
    zip_path = DIST / "Yaw-Yaw-Portable-v2.0.zip"
    log(f"Creating portable zip: {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(APP_DIR):
            for file in files:
                abs_p = Path(root) / file
                rel_p = Path("Yaw-Yaw") / abs_p.relative_to(APP_DIR)
                zf.write(abs_p, rel_p)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    log(f"SUCCESS: Portable zip created -> {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def main():
    log("=== Starting Yaw-Yaw Standalone Packaging ===")
    step1_ensure_icon()
    step2_compile_launcher()
    step3_assemble_portable_payload()
    step4_verify_portable_payload()
    iss = step5_generate_inno_script()
    setup_exe = step6_compile_inno_installer(iss)
    zip_pkg = step7_create_portable_zip()

    print("\n" + "=" * 60, flush=True)
    print("YAW-YAW STANDALONE PACKAGING COMPLETE!", flush=True)
    print("=" * 60, flush=True)
    if setup_exe and setup_exe.is_file():
        print(f"1. Standalone Installer: {setup_exe} ({setup_exe.stat().st_size / (1024*1024):.1f} MB)", flush=True)
    if zip_pkg and zip_pkg.is_file():
        print(f"2. Portable Zero-Install ZIP: {zip_pkg} ({zip_pkg.stat().st_size / (1024*1024):.1f} MB)", flush=True)
    print(f"3. Portable App Folder: {APP_DIR}", flush=True)
    print("=" * 60 + "\n", flush=True)


if __name__ == "__main__":
    main()
