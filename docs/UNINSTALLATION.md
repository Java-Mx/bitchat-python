# Uninstalling BitChat (`v0.3.1`)

BitChat includes a built-in, cross-platform uninstallation engine (`bitchat.platform.uninstaller`) as well as native OS uninstaller hooks so you can cleanly remove BitChat regardless of how it was installed (Windows `.exe` installer, `pip`, `uv`, `pipx`, `.deb`, `AppImage`, or `Flatpak`).

---

## 1. Normal Uninstall vs. Complete Removal (User Data)

BitChat separates **application artifacts** from **user data** so that upgrading or reinstalling does not accidentally destroy your cryptographic identity:

| Mode | What Is Removed | What Is Preserved |
| :--- | :--- | :--- |
| **Normal Uninstall** *(Default)* | Standalone installation directories (`%LOCALAPPDATA%\Programs\BitChat`, `%ProgramFiles%\BitChat`), console-script launchers (`bitchat.exe`, `bitchat-script.py`, `bitchat.cmd`, `bitchat.ps1`, `bitchat`) across all discovered Python environments, `bitchat` / `bitchat_python-*.dist-info` packages, Desktop/Start Menu/Startup shortcuts, Windows Registry uninstall keys, and BitChat-owned `PATH` entries. | Preserves `~/.bitchat/` (`%USERPROFILE%\.bitchat\` on Windows), keeping `identity.json`, `config.json`, and `bitchat.log`. |
| **Complete Removal** (`--remove-user-data` / `--purge`) | Everything removed by a Normal Uninstall **plus** permanent deletion of `~/.bitchat/` (`identity.json`, `identity.json.lock`, `config.json`, trusted contact fingerprints, and diagnostic logs). | Nothing — all BitChat files and keys are removed from the user account. |

> ** Note on Developer Git Checkouts:** The built-in uninstaller automatically detects developer source checkouts (directories containing both `.git` and `pyproject.toml`) and **never** deletes files inside a developer repository checkout.

---

## 2. Using the Built-In CLI Uninstaller (Windows & Linux)

The fastest way to remove all installed BitChat binaries and console-script launchers from your machine is via the `bitchat --uninstall` command:

### 2.1 Preview What Will Be Removed (Dry Run)

Run a non-destructive dry run first to see every file, directory, shortcut, registry key, and `PATH` entry that BitChat detected on your system:

```bash
# Preview normal uninstall (preserves ~/.bitchat)
bitchat --uninstall --dry-run

# Preview complete uninstall (including ~/.bitchat user data)
bitchat --uninstall --remove-user-data --dry-run
```

### 2.2 Run Normal Uninstall (Preserve `~/.bitchat`)

```bash
bitchat --uninstall
```

### 2.3 Run Complete Uninstall (Delete `~/.bitchat` Identity & Config)

Interactive confirmation:

```bash
bitchat --uninstall --remove-user-data
```

Non-interactive / automated confirmation (requires `--yes` / `-y`):

```bash
bitchat --uninstall --remove-user-data --yes
# Equivalent alias:
bitchat --uninstall --purge --yes
```

---

## 3. Windows Uninstallation Guide

### 3.1 Why `bitchat` Sometimes Remained on `PATH` After Uninstalling Older Versions

If you previously installed BitChat using **both** the standalone Windows installer (`%LOCALAPPDATA%\Programs\BitChat\bitchat.exe`) **and** `pip install` inside one or more Python installations (for example, `C:\Users\<user>\AppData\Local\Programs\Python\Python314\Scripts\bitchat.exe`), running only the Windows installer's uninstaller in older releases removed the standalone folder while leaving `Python314\Scripts\bitchat.exe` on your `PATH`.

In **BitChat `v0.3.1`**, both `bitchat --uninstall` and the Windows Inno Setup uninstaller (`unins000.exe`) automatically scan all discovered Python `Scripts` directories, `PATH` locations, and site-packages to remove stray `bitchat.exe` console-script launchers so that `bitchat` is no longer recognized in new terminals after uninstalling.

### 3.2 Uninstalling via Windows Settings or `unins000.exe`

1. **Windows Installed Apps:**
   - Open **Windows Settings → Apps → Installed apps**.
   - Search for **BitChat**, click the `...` menu, and select **Uninstall**.
   - In interactive mode, the uninstaller will ask whether you also want to delete your user data and cryptographic identity keys in `%USERPROFILE%\.bitchat`. Choose **No** to keep your keys or **Yes** for complete removal.
2. **Direct Uninstaller Executable:**
   ```powershell
   # Interactive uninstall
   "$env:LOCALAPPDATA\Programs\BitChat\unins000.exe"

   # Silent unattended uninstall (preserves %USERPROFILE%\.bitchat)
   Start-Process -FilePath "$env:LOCALAPPDATA\Programs\BitChat\unins000.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
   ```
3. **WinGet Uninstall:**
   ```powershell
   winget uninstall Java-Mx.BitChat
   ```

### 3.3 How Self-Deletion Works on Windows

Because Windows locks a running `.exe` (`bitchat.exe` or `_bitchat_core.pyd`) while it is executing, `bitchat --uninstall` spawns a detached background cleanup helper process (`_schedule_windows_self_delete`) that waits for the parent process to exit and retries deletion across multiple passes. If a file remains locked by another process (such as an open terminal or antivirus scanner), BitChat registers it with `MoveFileExW(..., MOVEFILE_DELAY_UNTIL_REBOOT)` and notes the pending reboot deletion in the uninstall report.

### 3.4 Verifying Clean Removal on Windows

Open a **new** PowerShell window (so updated environment variables take effect) and run:

```powershell
Get-Command bitchat -ErrorAction SilentlyContinue
where.exe bitchat
```

Neither command should return a result.

---

## 4. Linux Uninstallation Guide

### 4.1 Debian / Ubuntu Package (`.deb`)

- **Remove application only (preserve `~/.bitchat/`):**
  ```bash
  sudo apt remove bitchat
  ```
- **Complete purge (remove package and system configuration, then remove user data):**
  ```bash
  sudo apt purge bitchat
  rm -rf ~/.bitchat
  ```

### 4.2 AppImage

AppImages are self-contained single-file binaries that do not install system-wide libraries:

```bash
# Remove the AppImage file
rm -f ./BitChat-0.3.1-x86_64.AppImage

# Optional: remove desktop integration and user data
rm -f ~/.local/share/applications/bitchat.desktop
rm -rf ~/.bitchat
```

### 4.3 Flatpak

- **Remove the Flatpak application:**
  ```bash
  flatpak uninstall io.github.java_mx.bitchat
  ```
- **Remove the Flatpak application and its sandboxed data:**
  ```bash
  flatpak uninstall --delete-data io.github.java_mx.bitchat
  rm -rf ~/.bitchat
  ```

---

## 5. Python Package Manager Uninstall (`pip`, `uv`, `pipx`)

If you prefer using your Python package manager directly instead of `bitchat --uninstall`:

```bash
# Standard pip
pip uninstall bitchat-python

# Astral uv tool environment
uv tool uninstall bitchat-python

# pipx isolated environment
pipx uninstall bitchat-python
```

If you installed `bitchat-python` across multiple Python versions on the same machine (`python3.10`, `python3.12`, `python3.14`, etc.), running `bitchat --uninstall` will clean up all discovered non-checkout Python installations in a single step.

---

## 6. Safe `PATH` Cleanup Guarantee

When modifying the user `PATH` (in the Windows Registry under `HKCU\Environment` or in POSIX shell profiles), BitChat enforces a strict safety check (`_is_bitchat_owned_install_dir`):

- **Removed from `PATH`:** Dedicated BitChat directories such as `%LOCALAPPDATA%\Programs\BitChat` or `C:\Program Files\BitChat`.
- **Never Removed from `PATH`:** Shared directories such as `Python3XX\Scripts`, `C:\Windows\System32`, `/usr/local/bin`, or `~/.local/bin` are **never** removed from your `PATH`. Inside shared directories, BitChat deletes only the individual `bitchat*` launcher files (`bitchat.exe`, `bitchat-script.py`, `bitchat`).
