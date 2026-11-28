"""STP-080 / vlna 36 — deterministická reference datová sada pro parser ``syslog``.

Jedna textová fixtura (§7 pilot, design §7):

- ``syslog_sample.log`` — Unix BSD syslog (RFC 3164) řádky
  ``MMM DD HH:MM:SS host process[pid]: zpráva``.

Determinismus: pevné hosty/časy/PID/zprávy, LF řádky, UTF-8 bez BOM; SHA-256 pin
fixtury se zapisuje do manifestu (fail-fast proti driftu důkazu).

Pokrýtý kontrakty: den s mezerou i nulově doplněn (``Nov  7`` / ``Nov 07`` →
pole ``date="Nov 07"``), PID přítomen/absent (explicitní None, §3.3), duplicitní
join klíč host+process+date+time (§3.2 — páruje se po sobě), dvojtečky v zprávě
(první „: " = oddělovač), velká/písmena s pomlčkou v procesu, UTF-8 diakritika,
přeskočení pokračování záznamu (odstavec) a prázdného řádku.

Golden ``expected_syslog_sample.json`` = normalizované záznamy (§3
``domain/differential.normalize_dataset``) referenční cesty — nezávislá STOPA
cesta musí produkovat byte-stejný tvar po JSON serializaci (E2E test STP-080).

Běh: ``python build_fixture.py [outdir]`` (výchozí = adresář tohoto skriptu).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SYSLOG_SAMPLE = """\
Nov 17 09:15:32 web-01 sshd[2481]: Accepted publickey for deploy from 10.0.0.5 port 51234 ssh2: RSA SHA256:abc123
Nov 17 09:15:32 web-01 sudo[2482]: deploy : TTY=pts/0 ; PWD=/home/deploy ; USER=root ; COMMAND=/usr/bin/systemctl restart nginx
Nov 17 09:16:01 web-01 CRON[2500]: (root) CMD (/usr/local/bin/backup.sh)
Nov  7 23:58:41 db-01 postgres[1102]: checkpoint complete: wrote 1234 buffers (7.6%)
Nov  7 23:59:02 db-01 systemd-logind: New session 42 of user appuser
Nov 07 23:59:02 db-01 kernel: [UFW BLOCK] IN=eth0 OUT= MAC=aa:bb:cc:dd:ee:ff PROTO=TCP DPT=8080
    at com.example.pipeline.Stage.run(Stage.java:42)

Nov 17 09:20:00 web-01 nginx[3300]: 2026/11/17 09:20:00 [error] 3301#0: *548 connect() failed (111: Connection refused)
Nov 17 09:20:00 web-01 nginx[3300]: upstream server temporarily disabled
Nov 17 09:21:15 web-01 php-fpm[4100]: [pool www] child exited on signal 11; status=success: retry scheduled
Nov 18 08:00:01 web-01 systemd[1]: Started Daily apt upgrade and clean activities.
Nov 18 08:05:33 db-01 app-server: připojení k databázi navázáno (latence 42 ms)
"""


def main(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    target = outdir / "syslog_sample.log"
    data = SYSLOG_SAMPLE.encode("utf-8")
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")
    print(f"sha256={hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
