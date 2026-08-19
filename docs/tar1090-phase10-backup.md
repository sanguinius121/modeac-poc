# tar1090 Phase 10 backup and rollback

Backup created (UTC): `2026-08-10T09:13:13Z`

Backup directory: `/home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z`

The backup was verified with `cmp` and SHA256 before any source edit. The production tar1090 files are root-owned; deploying or rolling back them requires sudo.

| Original / modified target | Backup | Original SHA256 |
|---|---|---|
| `/usr/local/share/tar1090/html/index.html` | `usr-local-share-tar1090-html/index.html` | `1c616be3ca30ada8aa25bb7bcb5bdc0f4ad956b50985563365e258f38de65e59` |
| `/home/mlatserver/modeac-poc/realtime/api.py` | `home-mlatserver-modeac-poc-realtime/api.py` | `8b16731a08d0af80baecd8c89fbf96ce396a8044485ed6442b3c4aae34faf354` |

The following production targets are new files and therefore have no original payload:

- `/usr/local/share/tar1090/html/poc-mlat-overlay.js`
- `/usr/local/share/tar1090/html/poc-mlat-overlay.css`

Run the prepared rollback script from an interactive account with sudo rights:

```bash
/home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z/rollback.sh
```

Equivalent commands are:

```bash
sudo install -o root -g root -m 0644 /home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z/usr-local-share-tar1090-html/index.html /usr/local/share/tar1090/html/index.html
sudo rm -f /usr/local/share/tar1090/html/poc-mlat-overlay.js /usr/local/share/tar1090/html/poc-mlat-overlay.css
install -m 0644 /home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z/home-mlatserver-modeac-poc-realtime/api.py /home/mlatserver/modeac-poc/realtime/api.py
```

Static tar1090 files do not require a service restart. Hard-refresh open browser tabs after rollback. If the PoC backend is running, restart only that PoC process so the restored CORS list takes effect. Do not restart or reconfigure readsb, mlat-server, or receiver forwarding.
