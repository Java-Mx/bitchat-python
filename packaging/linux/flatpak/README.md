# BitChat Flatpak Packaging

This directory contains the production Flatpak packaging manifest and AppStream metadata for BitChat, configured for submission to [Flathub](https://flathub.org).

## Application ID

- **Application ID:** `io.github.java_mx.bitchat`
- **Reverse-DNS Root:** Derived from the authoritative GitHub organization namespace `https://github.com/Java-Mx`.

## Permission Audit & Security Rationale

BitChat employs a strictly scoped permission model adhering to the principle of least privilege:

| Permission | Technical Requirement | Justification |
| :--- | :--- | :--- |
| `--share=network` | LAN Discovery & TCP Messaging | Required for UDP broadcast/multicast peer discovery on port `24024` and direct peer-to-peer TCP messaging connections on port `24025`. |
| `--system-talk-name=org.bluez` | Bluetooth Low Energy Mesh | Required for the application to communicate with the host BlueZ system daemon over the D-Bus system bus to discover adapters, scan for BLE peers, host peripheral advertisements, and manage GATT services. |

### Filesystem Permissions

BitChat does **not** request `--filesystem=host` or `--filesystem=home`. 
The application strictly stores user preferences in `$XDG_CONFIG_HOME/bitchat` and identity keys in `$XDG_DATA_HOME/bitchat`. Flatpak isolates these within the per-application sandbox container (`~/.var/app/io.github.java_mx.bitchat/`), guaranteeing cryptographic and privacy isolation.

## Building Locally

Ensure `flatpak` and `flatpak-builder` are installed on your Linux distribution:

```bash
# Ubuntu / Debian
sudo apt install flatpak flatpak-builder

# Install required Freedesktop 24.08 runtime and SDK
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08
```

### Build and Install

```bash
cd packaging/linux/flatpak

# Build the flatpak bundle into build-dir
flatpak-builder --force-clean build-dir io.github.java_mx.bitchat.yaml

# Install for current user
flatpak-builder --user --install --force-clean build-dir io.github.java_mx.bitchat.yaml

# Run BitChat
flatpak run io.github.java_mx.bitchat
```

### Uninstall

```bash
flatpak uninstall io.github.java_mx.bitchat
```

## AppStream Metadata Validation

Validate the AppStream metadata file using `appstreamcli`:

```bash
appstreamcli validate io.github.java_mx.bitchat.metainfo.xml
```
