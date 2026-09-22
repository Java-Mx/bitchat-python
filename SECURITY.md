# Security Policy

## Early Development Notice

> [!WARNING]
> `bitchat-python` is currently in active early development. No formal third-party security audit has been performed on this codebase or its cryptographic implementations. Use in high-risk or production privacy contexts is not advised at this stage.

## Reporting a Vulnerability

We take the security of `bitchat-python` and the BitChat protocol seriously. If you discover a vulnerability or potential security flaw, **do NOT disclose it publicly** through GitHub issues, discussions, pull requests, or social media. Public disclosure puts all users and nodes at risk before a fix can be made available.

### How to Report Privately

Please report security issues privately through **GitHub Security Advisories**:

1. Go to the repository's **Security** tab on GitHub.
2. Select **Advisories** from the left-hand navigation.
3. Click **Report a vulnerability** to open a private draft advisory.
4. Fill in the details of the vulnerability, including reproduction steps and potential impact.

If GitHub Security Advisories are inaccessible, please reach out directly to the project maintainers via secure private channels before releasing any technical details.

### What to Include

To help us investigate and remediate the issue effectively, please include:
- A detailed description of the vulnerability and its potential impact.
- Affected modules (e.g., protocol framing, cryptography, BLE transport, peer session state).
- Clear reproduction steps or a minimal proof-of-concept (PoC).
- Environment details: Operating system, Python version, BLE hardware/stack, and dependencies.
- Any suggested patches or mitigations, if known.

## Scope

### In Scope
The following security-sensitive areas are within scope for vulnerability reporting:
- **Cryptography**: Flaws in cryptographic primitives, encryption/decryption routines, signing, key exchange, or insecure entropy generation.
- **Authentication & Peer Verification**: Bypass of node authentication, identity spoofing, or session hijacking.
- **BLE Pairing & Transport Security**: Vulnerabilities in Bluetooth Low Energy pairing, link security, replay attacks, or man-in-the-middle (MITM) vulnerabilities.
- **Key Management**: Insecure generation, storage, transmission, or zeroization/cleanup of private keys, pre-shared secrets, and session keys.
- **Protocol Vulnerabilities**: BitChat protocol logic errors, malformed packet parsing, state machine desync, denial-of-service against peers, or route manipulation.
- **Data Exposure**: Unintended leakage of plaintext messages, sensitive metadata, contact identity keys, or connection logs.

### Out of Scope (What NOT to Report Here)
Please do **NOT** submit security vulnerability reports for:
- General bugs, crashes, exceptions, or unexpected behavior without security implications (please use standard GitHub Issues).
- Feature requests, protocol design enhancements, or usability suggestions.
- Vulnerabilities requiring physical access to an unlocked host machine or existing root/administrator compromise.
- Social engineering or phishing targeting project contributors or users.
- Vulnerabilities in upstream operating systems or third-party hardware Bluetooth controllers, unless an actionable workaround or mitigation is applicable within `bitchat-python`.

## Response Timeline Expectations

We are committed to handling all valid security reports responsibly and efficiently:
- **Initial Acknowledgment**: Within 48 hours of report submission.
- **Triage & Assessment**: Within 5 business days, confirming severity and reproducibility.
- **Fix & Remediation**: Critical security issues will receive highest priority for patching in an expedited release.
- **Coordinated Disclosure**: Public advisories and release notes detailing the issue will only be published after a fix is verified and deployed, or through mutual agreement with the reporter.

Thank you for responsibly reporting security vulnerabilities and helping keep BitChat secure!
