# VideoEditor panel

A multi-user panel for teams that publish video to many YouTube channels. It prepares
variations of a video, uploads in batches through the YouTube Data API, keeps track of
each channel's quota, and hands campaigns over to an analytics tracker.

In daily production use. The interface is in Russian.

## What it handles

- **OAuth 2.0 per channel**, with token refresh and recovery from expired grants.
- **Quota accounting.** When a channel hits its daily API limit in the middle of a batch,
  the remainder continues on the next channel instead of failing the whole run.
- **Several users at once**, each with an isolated workspace; access is checked on the server.
- **Video preparation with FFmpeg** before upload.
- **Tracker integration over REST**: campaigns are created from the panel.
- **Install without a terminal.** On first start the app installs its own dependencies.
- **In-app update.** The panel replaces `app.py` with the current one from this repository.

## Run

```bash
python3 app.py
```

The panel opens on http://localhost:7777 (override with `VE_PORT`). Non-technical users
start from `install_mac.command` or `install_windows.bat`.

## Tests

```bash
python3 selftest.py
```

The self-test uploads nothing and does not touch production data: the YouTube upload is
mocked and temporary files go to `/tmp`. It covers the places that have actually broken —
proxy string parsing, title variations, the FFmpeg filters, all three batch modes, and the
wording of user-facing errors.

## Why one file

`app.py` is a single file for a practical reason: the in-app updater ships a release by
replacing exactly one file, and a panel that has to work on a non-technical user's laptop
should have nothing else to get out of sync. It has grown large, and a staged split into
modules is under way. The reusable part of the design — roles, resources with limits,
capacity-aware dispatch — already lives separately in
[panelcore](https://github.com/Rodenom/panelcore).
