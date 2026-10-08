# BitChat Snap Packaging Evaluation & Specification

This directory documents the technical evaluation, permissions model, and configuration for packaging BitChat via Canonical Snapcraft.

## Architectural Evaluation

Snap packages execute inside an AppArmor- and seccomp-confined sandbox managed by Canonical's `snapd`. 

For BitChat, two architectural constraints were evaluated:

### 1. Bluetooth Low Energy Access (`bluez` plug)
- To access BlueZ over D-Bus (`org.bluez`), a strictly confined snap must declare the `bluez` interface plug.
- Under Ubuntu / Canonical Snap Store policies, the `bluez` plug is classified as a privileged interface. It is **not** automatically connected upon installation.
- Users must manually authorize access after installation:
  ```bash
  sudo snap connect bitchat:bluez
  ```
- Automated connection in the public Snap Store requires a formal interface auto-connection grant request on the Snapcraft forum.

### 2. Peer-to-Peer LAN Discovery (`network-bind` & `network` plugs)
- BitChat requires listening on UDP port `24024` for LAN peer discovery broadcasts and listening on TCP port `24025` for incoming peer sessions.
- These operations require the standard `network` and `network-bind` interfaces.

## Current Support Matrix

- **Primary Native Target:** Debian / Ubuntu `.deb` (unrestricted native hardware access)
- **Primary Sandboxed Target:** Flathub Flatpak (`io.github.java_mx.bitchat`, automated BlueZ system-talk permission)
- **Universal Portable Target:** AppImage (zero-dependency standalone binary)
- **Snap:** Evaluated and maintained with `snapcraft.yaml`. Tracked as a secondary distribution format pending Snap Store manual assertion requirements.

## Building the Snap Locally

If you have `snapcraft` installed on an Ubuntu host or Multipass:

```bash
cd packaging/linux/snap
snapcraft

# Install locally
sudo snap install bitchat_0.1.0_amd64.snap --dangerous

# Connect required BlueZ interface
sudo snap connect bitchat:bluez

# Run BitChat
bitchat
```
