# Third-party: RustDesk

This product optionally bundles or downloads the **RustDesk** remote desktop client.

- Project: https://github.com/rustdesk/rustdesk
- Website: https://rustdesk.com/
- License: **GNU Affero General Public License v3.0 (AGPL-3.0)**

If a RustDesk binary is included under `vendor/rustdesk/`, the corresponding
source code is available from the upstream repository at the matching release tag.

Desktop Toolkit / QuakerParrotPet only launches RustDesk as a separate process;
we do not modify or statically link RustDesk.
