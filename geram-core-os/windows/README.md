# GERAM CORE OS on Windows

The Windows client is native Electron. The security-sensitive Python backend,
Pyright, Terminal Watcher, and A.R.E.S. runners execute in WSL2 so the same
Bubblewrap boundary used by the Linux release is preserved.

1. Run `GERAM-Windows-Setup.ps1` in PowerShell once.
2. Accept the WSL/Ubuntu 24.04 installation or restart request if Windows presents it.
3. Install and start the signed GERAM NSIS package.

The Electron client accepts only loopback traffic. User state is stored inside
the selected WSL user's `~/.local/share/geram-core-os`; Windows credentials or
project source are not copied into the application package. A Windows project
may be selected from WSL through `/mnt/c/...` when explicitly configured.
