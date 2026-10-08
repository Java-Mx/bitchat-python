# Linux Platform Architecture & Packaging Guide

This document details BitChat's Linux runtime architecture, D-Bus/BlueZ subsystem integration, LAN mesh networking, hardware capability detection, and distribution packages.

---

## 1. Runtime Architecture

BitChat operates across two independent local transport stacks on Linux:
1. **Bluetooth Low Energy (BLE) Mesh:** Powered by the `bleak` library interfacing directly with the Linux kernel's BlueZ daemon via the system D-Bus bus.
2. **Local Area Network (LAN) Mesh:** Direct peer discovery using UDP broadcast/multicast (port `24024`) and direct point-to-point TCP streaming connections (port `24025`).

All user data transferred over both transports is secured end-to-end using the Noise Protocol Framework (Noise XX handshake with Curve25519, ChaCha20-Poly1305 / AES-GCM, and BLAKE2s / SHA-256).

---

## 2. Bluetooth & BlueZ Subsystem

### BlueZ Daemon & D-Bus Bus
On Linux, Bluetooth adapters are managed exclusively by the `bluetoothd` service communicating over the system D-Bus bus:
- **Service Name:** `org.bluez`
- **Adapter Interface:** `org.bluez.Adapter1` (e.g., `/org/bluez/hci0`)
- **LE Advertising Interface:** `org.bluez.LEAdvertisingManager1`
- **GATT Service Manager:** `org.bluez.GattManager1`

### Capability Distinctions
BitChat strictly avoids the assumption that an existing Bluetooth adapter supports all BLE roles. At runtime, BitChat performs capability classification:
- **BLE Central (Scanning & Inbound Connections):** Supported when `Adapter1` is powered on and `StartDiscovery` succeeds.
- **BLE Peripheral (Hosting Announcements):** Requires `LEAdvertisingManager1` on the adapter. On older kernels or adapters lacking LE advertisement offload, peripheral hosting is disabled while central scanning remains active.
- **GATT Hosting:** Requires `GattManager1` on the adapter.

### User Permissions & D-Bus Policy
Access to the system Bluetooth D-Bus endpoints is controlled by `/etc/dbus-1/system.d/bluetooth.conf`.
- Standard non-root users must belong to the `bluetooth` or `netdev` group, or possess an active seat granted by `systemd-logind` / polkit.
- If a user runs BitChat without permissions, D-Bus returns `org.freedesktop.DBus.Error.AccessDenied`. BitChat catches this and marks Bluetooth as `Permission denied` without crashing.

To grant user access:
```bash
sudo usermod -aG bluetooth $USER
```

---

## 3. LAN Subsystem & Firewall Rules

LAN transport operates directly over local subnets (Wi-Fi and Ethernet):
- **Peer Discovery:** UDP broadcasts sent to `255.255.255.255` on port `24024`.
- **Peer Messaging:** TCP server bound to port `24025`.

### Firewall Ports
Ensure local firewall rules permit traffic on these ports:
```bash
# UFW
sudo ufw allow 24024/udp comment 'BitChat Discovery'
sudo ufw allow 24025/tcp comment 'BitChat Transport'

# Firewalld
sudo firewall-cmd --add-port=24024/udp --permanent
sudo firewall-cmd --add-port=24025/tcp --permanent
sudo firewall-cmd --reload
```

---

## 4. Hardware Diagnostics (`/configure`)

BitChat includes an automated hardware discovery and capability diagnostics engine (`src/bitchat/platform/capabilities.py`).

Running `/configure` within the chat or `bitchat --configure` from the shell inspects:
- **System:** OS, Linux distribution (via `platform.freedesktop_os_release`), machine architecture, and Python runtime.
- **Bluetooth:** Primary adapter, BlueZ daemon availability, BLE Central capability, BLE Peripheral capability, GATT support, and D-Bus permissions.
- **Network:** Active Wi-Fi SSID, Ethernet interface state, local IPv4, and IPv6 address.
- **LAN:** UDP discovery socket binding (port `24024`) and TCP transport socket binding (port `24025`).
- **Transport Viability:** Evaluates and configures active transports according to detected hardware capabilities.

```bash
bitchat --configure
```

---

## 5. Linux Distribution Packages

### 1. Debian / Ubuntu Native Package (`.deb`)
- **Target:** Debian 12+, Ubuntu 22.04+, Linux Mint, Pop!_OS.
- **Architecture:** `amd64`.
- **Install Path:** `/usr/lib/bitchat/` with `/usr/bin/bitchat` launcher and `/usr/share/applications/bitchat.desktop`.
- **Installation:**
  ```bash
  sudo apt install ./bitchat_<version>_amd64.deb
  ```
- **Builder:** [`packaging/linux/deb/build_deb.py`](../../packaging/linux/deb/build_deb.py) (supports `dpkg-deb` and pure-Python POSIX `ar` packaging).

### 2. Flathub Flatpak (`io.github.java_mx.bitchat`)
- **Target:** Universal sandboxed desktop.
- **Permissions:** `--share=network`, `--system-talk-name=org.bluez`.
- **Sandbox Security:** Strictly confined. No broad host filesystem permissions.
- **Manifest:** [`packaging/linux/flatpak/io.github.java_mx.bitchat.yaml`](../../packaging/linux/flatpak/io.github.java_mx.bitchat.yaml).
- **AppStream Metainfo:** [`packaging/linux/flatpak/io.github.java_mx.bitchat.metainfo.xml`](../../packaging/linux/flatpak/io.github.java_mx.bitchat.metainfo.xml).

### 3. Portable AppImage (`BitChat-<version>-x86_64.AppImage`)
- **Target:** Universal portable single-file binary.
- **Features:** Self-contained runtime, no external dependencies, universal POSIX runner.
- **Builder:** [`packaging/linux/appimage/build_appimage.py`](../../packaging/linux/appimage/build_appimage.py).

### 4. Canonical Snapcraft (`bitchat`)
- **Target:** Canonical Snap Store.
- **Confinement:** Strict.
- **Interfaces:** `network`, `network-bind`, `bluez`.
- **Evaluation:** Because `bluez` requires manual store assertion or manual user connection (`sudo snap connect bitchat:bluez`), Snap is maintained as a documented secondary target.
- **Manifest:** [`packaging/linux/snap/snapcraft.yaml`](../../packaging/linux/snap/snapcraft.yaml).
