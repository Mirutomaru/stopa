"""CLI — forenzní analýzy (decrypt/FDE, paměťová forensika, mobilní ingest, pcap, anti-forensika).

P1-4 (refaktor god-file ``cli.py``): přesunuto bez změny chování;
facade ``stopa.cli`` re-exportuje implementace pro kompatibilitu.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from stopa.models import EvidenceSource

from .._util import _open_db, _print_json, _rich_progress


def cmd_decrypt(args: argparse.Namespace) -> int:
    """F1.1 — BitLocker / FileVault dešifrování (libbde/libfvde + STOPABLOCK).

    Detekce podle ``--type`` a magic na offsetu 0:
      * STOPABLK → syntetický whole-volume formát (čistý Python, AES-XTS)
      * bitlocker → reálný BVE obraz přes libbde (recovery key primární cesta)
      * filevault → Apple FDE přes libfvde (heslo)

    Výsledek = RAW plaintext do souboru (default: <obraz>.decrypted.img).
    """
    from stopa.data import bde_fvde
    from stopa.domain.fde_bitlocker import (
        FdeError,
        decrypt_block_stream,
        is_bitlocker_image,
    )

    # P0.3 — jednotná správa dočasných dešifrovaných obrazů (registry + audit)
    from stopa.domain.temp_images import release_temp

    img_path = Path(args.image).expanduser()
    if not img_path.is_file():
        print(f"Obraz neexistuje: {img_path}", file=sys.stderr)
        return 2

    out_path = (
        Path(args.out).expanduser()
        if args.out
        else img_path.with_suffix(".decrypted.img")
    )

    try:
        with open(img_path, "rb") as f:
            head = f.read(36)

        if is_bitlocker_image(head):
            # syntetický STOPABLOCK — credential z recovery key nebo hesla
            cred = args.recovery_key or args.password
            if not cred:
                print("Zadejte --recovery-key nebo --password", file=sys.stderr)
                return 2
            tmp_path, header = decrypt_block_stream(img_path, cred)
            try:
                tmp_path.replace(out_path)
            except OSError:
                release_temp(tmp_path)  # P0.3 — plaintext uvolnit z registru (zero-fill + unlink)
                raise
            release_temp(tmp_path)  # P0.3 — po replace() soubor pryč, zbývá auditní registrace
            size = out_path.stat().st_size
            desc = f"STOPABLOCK ({header.fs_type}, AES-XTS-{header.key_len // 2}) — dešifrováno {size / 1e6:.2f} MB"
        elif args.type == "bitlocker":
            if not bde_fvde.bde_available():
                print("Chybí libbde (nainstalujte runtime knihovnu — viz STOPA_BDE_LIB)", file=sys.stderr)
                return 3
            res = bde_fvde.decrypt_bitlocker(img_path, password=args.password, recovery_key=args.recovery_key)
            try:
                res.plaintext_path.replace(out_path)
            except OSError:
                release_temp(res.plaintext_path)  # P0.3 — plaintext uvolnit z registru (zero-fill + unlink)
                raise
            release_temp(res.plaintext_path)  # P0.3 — po replace() soubor pryč, zbývá auditní registrace
            size = out_path.stat().st_size
            desc = f"{res.description} — {size / 1e6:.2f} MB"
        elif args.type == "filevault":
            if not bde_fvde.fvde_available():
                print("Chybí libfvde (nainstalujte runtime knihovnu — viz STOPA_BDE_LIB)", file=sys.stderr)
                return 3
            if not args.password:
                print("FileVault vyžaduje --password", file=sys.stderr)
                return 2
            res = bde_fvde.decrypt_filevault(img_path, password=args.password)
            try:
                res.plaintext_path.replace(out_path)
            except OSError:
                release_temp(res.plaintext_path)  # P0.3 — plaintext uvolnit z registru (zero-fill + unlink)
                raise
            release_temp(res.plaintext_path)  # P0.3 — po replace() soubor pryč, zbývá auditní registrace
            size = out_path.stat().st_size
            desc = f"{res.description} — {size / 1e6:.2f} MB"
        else:
            print(
                "Neznámý typ obrazu — zadejte --type bitlocker|filevault (nebo je to STOPABLOCK)",
                file=sys.stderr,
            )
            return 4
    except FdeError as e:
        print(f"FDE dešifrování selhalo: {e}", file=sys.stderr)
        return 1
    except bde_fvde.BdeError as e:
        print(f"BitLocker dešifrování selhalo: {e}", file=sys.stderr)
        return 1
    except bde_fvde.FvdeError as e:
        print(f"FileVault dešifrování selhalo: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        _print_json({"image": str(img_path), "out": str(out_path), "description": desc})
    else:
        print(desc)
        print(f"Plaintext: {out_path}")
    return 0


def cmd_memory_analyze(args: argparse.Namespace) -> int:
    """F1.2 — Memory Forensics přes Volatility 3 (ROADMAP V2 Fáze 1).

    Spustí vybrané vol pluginy na memory dumpu, mapuje JSON výstup na
    STOPA artefakty + cross-plugin anomaly rules a ukládá do case DB
    (idempotentní replace per file). PII zásada: surové credential material
    se neukládá — jen typ + fingerprint.

    Exit codes: 0 = OK · 1 = vol chyba · 2 = špatné argumenty · 3 = vol chybí
    """
    import hashlib

    from stopa.data import volatility as vol_mod
    from stopa.domain.mem_forensics import (
        DEFAULT_PLUGINS,
        MemForensicsError,
        apply_cross_plugin_rules,
        parse_plugin_output,
        summarize,
        validate_plugins,
    )
    from stopa.models import FileRecord

    json_mode = getattr(args, "json", False)
    dump_path = Path(args.dump).expanduser()
    if not dump_path.is_file():
        print(f"Memory dump neexistuje: {dump_path}", file=sys.stderr)
        return 2

    # explicitní --plugin má prioritu; jinak výchozí sada (pslist/netscan/ldrmodules/malfind)
    try:
        chosen = list(args.plugin or [])
        if args.with_defaults:
            chosen = list(DEFAULT_PLUGINS) + [p for p in chosen if p not in DEFAULT_PLUGINS]
        plugins = validate_plugins(chosen) if chosen else list(DEFAULT_PLUGINS)
    except MemForensicsError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not vol_mod.vol_available():
        msg = (
            "Volatility 3 není nainstalovaná — `pip install volatility3` do STOPA venv, "
            "nebo STOPA_VOL_BIN=/cesta/k/vol"
        )
        if json_mode:
            _print_json({"error": msg})
        else:
            print(msg, file=sys.stderr)
        return 3

    db = _open_db(args.case_id)
    try:
        # provenance: zdroj + soubor v DB (FK stability artefaktů).
        # Re-analyza stejného dumpu drží původní source → upsert_file konflikt
        # (source_id, rel_path) → replace_artifacts_for_file = idempotentní.
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(dump_path)), None
        )
        source = existing or EvidenceSource(case_id=args.case_id, kind="file", path=str(dump_path))
        if existing is None:
            db.add_source(source)
        sha256 = hashlib.sha256()
        with open(dump_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha256.update(chunk)
        rec = FileRecord(
            source_id=source.id,
            rel_path=dump_path.name,
            name=dump_path.name,
            size_bytes=dump_path.stat().st_size,
            sha256=sha256.hexdigest(),
            signature_type="memory_dump",
        )
        file_id = db.upsert_file(rec)

        bar = None if json_mode else _rich_progress()
        state: dict[str, object] = {"task": None}

        def _progress(done: int, total: int, label: str = "") -> None:
            if bar is not None:
                if state["task"] is None and total:
                    state["task"] = bar.add(label or f"vol {done}/{total}", total)
                elif state["task"] is not None:
                    bar.update(state["task"], done)  # type: ignore[arg-type]

        results = vol_mod.run_vol_plugins(
            str(dump_path), plugins, timeout_s=args.timeout, progress=_progress
        )

        all_arts: list = []
        plugin_errors: dict[str, str] = {}
        for plugin in plugins:  # deterministické pořadí (pořadí validace)
            res = results.get(plugin)
            if res is None:
                continue
            try:
                arts = parse_plugin_output(plugin, res.rows)
            except MemForensicsError as e:
                plugin_errors[plugin] = str(e)[:500]
                continue
            for a in arts:
                a.source_id = source.id
                a.file_id = file_id
                a.rel_path = dump_path.name
            all_arts.extend(arts)

        added_flags = apply_cross_plugin_rules(all_arts)
        db.replace_artifacts_for_file(file_id, all_arts)

        summary = summarize(all_arts)
        if not json_mode:
            print()
            print(f"  {summary['total']} artefaktů z {len(plugins)} pluginů "
                  f"(+{added_flags} anomaly flags)")
            for t, n in summary["by_type"].items():
                print(f"    {t}: {n}")
            if summary["anomaly_flags"]:
                print("  Anomalie: " + ", ".join(
                    f"{k}={v}" for k, v in summary["anomaly_flags"].items()
                ))
            for p_name, err in plugin_errors.items():
                print(f"  ! {p_name}: {err}", file=sys.stderr)

        if json_mode:
            _print_json({
                "dump": str(dump_path),
                "case_id": args.case_id,
                "file_id": file_id,
                "plugins_run": plugins,
                "plugin_errors": plugin_errors,
                **summary,
            })
        return 0 if not plugin_errors or all_arts else (1 if not all_arts else 0)
    finally:
        db.close()


@dataclass(frozen=True)
class _BytesHolder:
    """In-mem soubor z ZIP archivu (rel_path + bytes) — pro report.xml/VCF."""

    rel: str
    data: bytes


def cmd_import_mobile(args: argparse.Namespace) -> int:
    """F1.5 — Import mobilní extrakce (ROADMAP V2 Fáze 1).

    Podporované zdroje (--source):
      cellebrite — .ufd/.zip s report.xml (Cellebrite UFED evidence export),
                   volitelně i .vcf karty v archivu,
      msab       — .zip s .vcf kartami (MSAB XRY contacts export),
      adb        — složka Android logical dumpu; každá SQLite DB jde přes
                   existující extraktory (kontakty/WhatsApp msgstore/Signal).

    Artefakty do case DB idempotentně (replace per file), timeline events pro
    záznamy s časem, na konci korelace entit (AK: entity korelovány s
    existujícími kontakty případu).

    Exit codes: 0 = OK · 1 = nic neextrahováno / parse chyba · 2 = špatné argumenty
    """
    import hashlib
    import zipfile

    from stopa.domain.correlation import run_correlation
    from stopa.domain.mobile_forensics import (
        PARSER_VERSION,
        UfedParseError,
        contact_specs_from_card,
        models_to_artifact_specs,
        parse_ufdr_xml,
        parse_vcf,
    )
    from stopa.models import Artifact, FileRecord

    json_mode = getattr(args, "json", False)
    dump_path = Path(args.dump).expanduser()
    source_kind = args.source

    # ── vstupní soubory per typ zdroje ───────────────────────────────
    # [(rel_path, bytes|None)] — bytes pro textové parsery, None = DB (path)
    inputs: list[tuple[str, _BytesHolder | Path]] = []
    parse_errors: dict[str, str] = {}

    def _hash_file(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if source_kind == "adb":
        if not dump_path.is_dir():
            print(f"ADB logical dump musí být složka: {dump_path}", file=sys.stderr)
            return 2
        for p in sorted(dump_path.rglob("*")):
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            rel = p.relative_to(dump_path).as_posix()
            if suf in (".db", ".sqlite"):
                inputs.append((rel, p))
            elif suf == ".vcf":
                inputs.append((rel, p))  # VCF z backupu (řídké, ale levné)
    else:
        if not dump_path.exists():
            print(f"Soubor neexistuje: {dump_path}", file=sys.stderr)
            return 2

        def _archive_members() -> list[tuple[str, bytes]] | None:
            """ZIP (.ufd/.zip) → [(rel_path, bytes)]; složka → [..] z disk."""
            if dump_path.is_dir():  # rozbalený export — procházíme přímo
                out = []
                for p in sorted(dump_path.rglob("*")):
                    if not p.is_file() or p.stat().st_size > 256 * (1 << 20):
                        continue
                    out.append((p.relative_to(dump_path).as_posix(), p.read_bytes()))
                return out
            if dump_path.suffix.lower() in (".zip", ".ufd"):
                try:
                    with zipfile.ZipFile(dump_path) as zf:
                        return [
                            (zi.filename, zf.read(zi))
                            for zi in zf.infolist()
                            if not zi.is_dir() and zi.file_size <= 256 * (1 << 20)
                        ]
                except zipfile.BadZipFile as e:
                    print(f"Neplatné ZIP/UFDR archív: {e}", file=sys.stderr)
                    return None
            print(
                f"Nerozpoznaný formát pro --source {source_kind} "
                "(očekávám .ufd/.zip/složku): " + str(dump_path),
                file=sys.stderr,
            )
            return None

        members = _archive_members()
        if members is None:
            return 2
        for rel, data in members:
            low = rel.lower()
            if source_kind == "cellebrite" and (low.endswith("report.xml") or ".vcf" in low) or source_kind == "msab" and low.endswith(".vcf"):
                inputs.append((rel, _BytesHolder(rel, data)))

    if not inputs:
        msg = (
            f"Žádné vstupní soubory pro --source {source_kind} v {dump_path}"
            + (" (očekávám report.xml)" if source_kind == "cellebrite" else "")
            + (" (očekávám *.vcf)" if source_kind == "msab" else "")
        )
        print(msg, file=sys.stderr)
        return 2

    db = _open_db(args.case_id)
    try:
        # provenance: zdroj podle cesty (re-import → stejný source, idempotentní)
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(dump_path)), None
        )
        kind = "folder" if source_kind == "adb" else "file"
        source = existing or EvidenceSource(case_id=args.case_id, kind=kind, path=str(dump_path))
        if existing is None:
            db.add_source(source)

        # F1.4 pitfall — re-ingest: timeline events (FK artifact_id bez ON DELETE)
        # se vyčistí PŘED replace artifactů, jinak visící reference.
        if existing is not None:
            db.clear_timeline_events(source_id=source.id)

        all_arts: list[Artifact] = []
        file_ids: dict[str, str] = {}  # rel_path → file_id (idempotentní upsert)

        for rel, holder in inputs:
            size = len(holder.data) if isinstance(holder, _BytesHolder) else holder.stat().st_size
            sha = hashlib.sha256(holder.data).hexdigest() if isinstance(
                holder, _BytesHolder) else (_hash_file(holder))
            rec = FileRecord(
                source_id=source.id, rel_path=rel, name=Path(rel).name,
                size_bytes=size, sha256=sha, signature_type=None,
            )
            file_id = db.upsert_file(rec)
            file_ids[rel] = file_id

            arts_for_file: list[Artifact] = []
            if isinstance(holder, _BytesHolder):
                data = holder.data
                low = rel.lower()
                try:
                    specs: list = []
                    if low.endswith("report.xml"):
                        models, unknown = parse_ufdr_xml(data)
                        specs = models_to_artifact_specs(models)
                        if unknown:
                            note = "neznámé typy: " + ",".join(sorted(set(unknown))[:8])
                            parse_errors[rel] = (parse_errors.get(rel, "") + " " + note).strip()
                    elif low.endswith(".vcf"):
                        text = data.decode("utf-8", errors="replace")
                        cards = parse_vcf(text)
                        specs = [s for card in cards for s in contact_specs_from_card(card, engine=source_kind)]
                except (UfedParseError, UnicodeDecodeError) as e:
                    parse_errors[rel] = str(e)[:300]
                    continue
                arts_for_file = [
                    Artifact(artifact_type=s.artifact_type, title=s.title,
                             timestamp=s.timestamp, details=dict(s.details),
                             parser_version=f"import-mobile/{PARSER_VERSION}")
                    for s in specs
                ]
            else:  # adb: SQLite DB / VCF z disku
                if holder.suffix.lower() == ".vcf":
                    text = holder.read_text(encoding="utf-8", errors="replace")
                    cards = parse_vcf(text)
                    arts_for_file = [
                        Artifact(artifact_type=s.artifact_type, title=s.title,
                                 timestamp=s.timestamp, details=dict(s.details),
                                 parser_version=f"import-mobile/{PARSER_VERSION}")
                        for card in cards for s in contact_specs_from_card(card, engine="adb")
                    ]
                else:
                    from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts

                    arts_for_file = [
                        a.model_copy(deep=True) for a in extract_sqlite_artifacts(holder)
                    ]
                    if not arts_for_file and holder.suffix.lower() != ".db":
                        pass  # generic triage vrací [] jen pro neznámé schéma — OK

            for a in arts_for_file:
                a.source_id = source.id
                a.file_id = file_id
                a.rel_path = rel
            db.replace_artifacts_for_file(file_id, arts_for_file)
            all_arts.extend(arts_for_file)

        # timeline events (po artifactech — FK artifact_id musí existovat)
        tl_count = 0
        for a in all_arts:
            if a.timestamp is None:
                continue
            db.add_timeline_event(
                source_id=source.id, artifact_id=a.id, file_id=a.file_id,
                rel_path=a.rel_path, event_type=a.artifact_type, ts_utc=a.timestamp,
                title=a.title, parser_version=f"import-mobile/{PARSER_VERSION}",
                anomaly_flags=list(a.anomaly_flags), ts_origin="source",
            )
            tl_count += 1

        db.commit()

        # AK: entity korelovány s existujícími kontakty případu
        corr = run_correlation(db, args.case_id)

        by_type: dict[str, int] = {}
        for a in all_arts:
            by_type[a.artifact_type] = by_type.get(a.artifact_type, 0) + 1

        if not json_mode:
            print(f"  {len(all_arts)} artefaktů ze {len(inputs)} souborů "
                  f"(timeline: {tl_count})")
            for t_name in sorted(by_type):
                print(f"    {t_name}: {by_type[t_name]}")
            if parse_errors:
                for rel, err in list(parse_errors.items())[:10]:
                    print(f"  ! {rel}: {err}", file=sys.stderr)
            print(
                f"Korelace entit: {corr['entities']} entit, "
                f"{corr['correlations_total']} propojení"
            )

        if json_mode:
            _print_json({
                "dump": str(dump_path),
                "case_id": args.case_id,
                "source_kind": source_kind,
                "files_processed": len(inputs),
                "artifacts": len(all_arts),
                "timeline_events": tl_count,
                "by_type": by_type,
                "parse_errors": parse_errors,
                **corr,
            })

        return 0 if all_arts else 1
    finally:
        db.close()


def cmd_pcap_analyze(args: argparse.Namespace) -> int:
    """F1.3 — Síťová forenzika přes Scapy (ROADMAP V2 Fáze 1).

    Přečte .pcap/.pcapng, reasambloví TCP streamy, extrahuje soubory z
    HTTP/FTP/SMB a detekuje IoC (DNS tunneling, C2 beaconing, …). Artefakty
    do case DB (idempotentní replace per file), surové body do
    <root>/extracted/<case_id>/network/. PII zásada: v DB jen fingerprint.

    Exit codes: 0 = OK · 1 = parse chyba · 2 = špatné argumenty · 3 = scapy chybí
    """
    import hashlib

    from stopa.data import pcap_io
    from stopa.domain.net_forensics import (
        PARSER_VERSION,
        detect_ftp,
        detect_smb,
        extract_http,
        reassemble_flows,
        run_ioc_rules,
    )
    from stopa.domain.net_forensics import (
        fingerprint_value as fingerprint_net_value,
    )
    from stopa.domain.net_forensics import (
        summarize as net_summarize,
    )
    from stopa.models import Artifact, FileRecord

    json_mode = getattr(args, "json", False)
    pcap_path = Path(args.pcap).expanduser()
    if not pcap_path.is_file():
        print(f"PCAP soubor neexistuje: {pcap_path}", file=sys.stderr)
        return 2

    if not pcap_io.scapy_available():
        msg = ("Scapy není nainstalovaná — `pip install scapy` do STOPA venv "
               "(volitelná runtime závislost pro F1.3)")
        if json_mode:
            _print_json({"error": msg})
        else:
            print(msg, file=sys.stderr)
        return 3

    db = _open_db(args.case_id)
    try:
        # provenance + idempotentní re-analyza (stejný pattern jako F1.2)
        existing = next(
            (s for s in db.list_sources(args.case_id) if s.path == str(pcap_path)), None
        )
        source = existing or EvidenceSource(case_id=args.case_id, kind="file", path=str(pcap_path))
        if existing is None:
            db.add_source(source)
        sha256 = hashlib.sha256()
        with open(pcap_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha256.update(chunk)
        rec = FileRecord(
            source_id=source.id,
            rel_path=pcap_path.name,
            name=pcap_path.name,
            size_bytes=pcap_path.stat().st_size,
            sha256=sha256.hexdigest(),
            signature_type="network_capture",
        )
        file_id = db.upsert_file(rec)

        bar = None if json_mode else _rich_progress()
        state: dict[str, object] = {"task": None}

        def _progress(done: int, total: int, label: str = "") -> None:
            if bar is not None and state["task"] is None and total:
                state["task"] = bar.add(label or "pcap", total)

        try:
            records = pcap_io.read_pcap(pcap_path, max_packets=args.max_packets)
        except pcap_io.PcapParseError as e:
            if json_mode:
                _print_json({"error": str(e)})
            else:
                print(f"PCAP parse chyba: {e}", file=sys.stderr)
            return 1

        _progress(1, 3, "TCP reassembly")
        streams = reassemble_flows(records)

        arts: list[Artifact] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        def _mk(atype: str, title: str, details: dict, flags: list[str] | None = None) -> Artifact:
            return Artifact(
                source_id=source.id, file_id=file_id, rel_path=pcap_path.name,
                artifact_type=atype, title=title, details=details,
                confidence=0.7 if flags else 0.9,
                parser_version=PARSER_VERSION, extracted_at=datetime.fromisoformat(now_iso),
                anomaly_flags=list(flags or []),
            )

        # 1) flow artefakty (reassembly výsledek — jen metadata + fingerprint)
        for key, st in streams.items():
            arts.append(_mk(
                "network_flow", f"TCP {key.label()}",
                {
                    "bytes": len(st.data),
                    "sha256_prefix": hashlib.sha256(st.data).hexdigest()[:16],
                    "packet_count": st.packet_count,
                    "first_time": st.first_time,
                    "last_time": st.last_time,
                },
            ))

        # 2) HTTP extrakce + FTP/SMB detekce → soubory do <case>/extracted/network/
        out_dir = db.path.parent / "extracted" / args.case_id / "network"
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for key, st in streams.items():
            http_files = extract_http(st.data[:1 << 20], key.label())
            for i, f_ in enumerate(http_files):
                safe_name = Path(f_.filename).name or f"body_{i}.bin"
                dest = out_dir / safe_name
                n = 1
                while dest.exists():
                    stem, suf = os.path.splitext(safe_name)
                    dest = out_dir / f"{stem}_{n}{suf}"
                    n += 1
                dest.write_bytes(f_.raw)
                written.append(str(dest))
                arts.append(_mk(
                    "file_extract_candidate", safe_name,
                    {
                        "size_bytes": f_.size_bytes,
                        "sha256_prefix": f_.sha256_prefix,
                        "content_type": f_.content_type,
                        "extracted_to": str(dest),
                        "flow": key.label(),
                    },
                ))
            ftp_cmds = detect_ftp(st.data[:1 << 20])
            if ftp_cmds:
                arts.append(_mk("ftp_command", f"FTP {key.label()}",
                                {"commands": ftp_cmds}, ["ftp_activity"]))
            smb_hits = detect_smb(st.data[:1 << 20])
            if smb_hits:
                arts.append(_mk("smb_session", f"SMB {key.label()}",
                                {"headers": smb_hits}, ["smb_activity"]))

        # 3) DNS query artefakty (unikátní QNAME + fingerprint)
        seen_qnames: set[str] = set()
        for r in records:
            if r.dns_qname and r.dns_qname not in seen_qnames:
                seen_qnames.add(r.dns_qname)
                arts.append(_mk("dns_query", r.dns_qname, {
                    "fingerprint": fingerprint_net_value(r.dns_qname),
                    "src_ip": r.src_ip,
                }))

        # 4) IoC pravidla → artefakty ioc_<pattern>
        _progress(2, 3, "IoC detekce")
        iocs = run_ioc_rules(records, streams)
        for hit in iocs["dns_tunneling"]:
            arts.append(_mk("ioc_dns_tunneling", str(hit.get("qname")),
                            dict(hit), ["dns_tunneling"]))
        for hit in iocs["c2_beaconing"]:
            arts.append(_mk("ioc_c2_beaconing",
                            f"{hit.get('dst_ip')}:{hit.get('dst_port')}",
                            dict(hit), ["c2_beaconing"]))
        for hit in iocs["http_ioc"]:
            arts.append(_mk(
                "ioc_http", str(hit.get("url") or hit.get("flow")),
                {"flow": hit.get("flow"), "flags": hit.get("flags")},
                list(hit.get("flags") or []),
            ))
        if iocs["unusual_high_port_tcp"]:
            arts.append(_mk("ioc_unusual_high_port", f"{len(iocs['unusual_high_port_tcp'])} flowů",
                            {"flows": iocs["unusual_high_port_tcp"]}, ["unusual_high_port"]))

        db.replace_artifacts_for_file(file_id, arts)

        stats = net_summarize(records)
        if not json_mode:
            print()
            print(f"  {len(arts)} artefaktů z {stats['total_packets']} paketů "
                  f"(tcp={stats.get('tcp', 0)}, udp={stats.get('udp', 0)}, dns={stats['dns_queries']})")
            if written:
                print(f"  extrahováno souborů: {len(written)} → {out_dir}")
        if json_mode:
            _print_json({
                "pcap": str(pcap_path),
                "case_id": args.case_id,
                "file_id": file_id,
                **stats,
                "artifacts": len(arts),
                "extracted_files": written,
                "ioc_counts": {
                    "dns_tunneling": len(iocs["dns_tunneling"]),
                    "c2_beaconing": len(iocs["c2_beaconing"]),
                    "http_ioc": len(iocs["http_ioc"]),
                    "unusual_high_port_tcp": len(iocs["unusual_high_port_tcp"]),
                },
            })
        return 0
    finally:
        db.close()


def cmd_antiforensics(args: argparse.Namespace) -> int:
    """F1.4 — Anti-Forensics detekce (ROADMAP V2 Fáze 1).

    Prohledá artefakty případu po stopech maskování důkazů: timestomping,
    log clearing (EVTX 1102 + mezery v záznamech), USN journal truncation,
    hidden partitions (MBR), LSB steganografie v PNG/JPG a signatury
    anti-forenzních nástrojů. Nálezy uloží jako artefakty ``antiforensics/<type>``
    s confidence + timeline alerty (idempotentní replace per scan).

    Exit codes: 0 = OK · 1 = analytická chyba · 2 = špatné argumenty
    """
    import re as _re

    from stopa.domain import anti_forensics as af
    from stopa.models import Artifact, FileRecord

    json_mode = getattr(args, "json", False)
    db = _open_db(args.case_id)
    try:
        # ── sběr vstupů — normalizace DB → dicty pro čistou doménovou vrstvu ──
        files_norm = [
            {
                "path": f.rel_path,
                "name": f.name,
                "mtime": f.mtime.isoformat() if f.mtime else None,
                "ctime": f.ctime.isoformat() if f.ctime else None,
                "atime": f.atime.isoformat() if f.atime else None,
            }
            for f in db.list_files()
        ]

        events_norm = []
        for a in db.list_artifacts(artifact_type="event_log_entry"):
            d = a.details or {}
            events_norm.append({
                "event_id": d.get("event_id"),
                "record_id": d.get("record_number"),
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            })

        usn_norm = []
        for a in db.list_artifacts(artifact_type="usn_record"):
            m = _re.match(r"^USN (\d+):", a.title or "")
            if not m:
                continue
            usn_norm.append({
                "usn": int(m.group(1)),
                "reason": (a.details or {}).get("reason") or "",
            })

        # stego kandidáti — PNG/JPG v případu, vyřešené přes cesty zdrojů
        sources = {s.id: s for s in db.list_sources(args.case_id)}
        stego_paths: list[str] = []
        for f in db.list_files():
            ext = (f.extension or "").lower().lstrip(".")
            if ext not in ("png", "jpg", "jpeg"):
                continue
            src = sources.get(f.source_id)
            if src is None:
                continue
            cand = Path(src.path).expanduser() / f.rel_path
            if cand.is_file():
                stego_paths.append(str(cand))

        # volitelný diskový obraz --image (MBR/partition table + integrity)
        img_p: Path | None = None
        header512: bytes | None = None
        image_size = 0
        image_ext = ""
        img_arg = getattr(args, "image", None)
        if img_arg:
            img_p = Path(img_arg).expanduser()
            if not img_p.is_file():
                msg = f"Diskový obraz neexistuje: {img_p}"
                print(msg, file=sys.stderr)
                return 2
            with open(img_p, "rb") as fh:
                header512 = fh.read(512)
            image_size = img_p.stat().st_size
            image_ext = img_p.suffix.lstrip(".").lower()

        # ── detekce (čistá doménová vrstva, bez I/O mimo stego/obraz) ──
        report = af.detect_anti_forensics(
            files=files_norm, events=events_norm, usn_records=usn_norm,
            image_path=str(img_p) if img_p else None,
            image_size_bytes=image_size, image_ext=image_ext,
            header512=header512, stego_paths=stego_paths,
        )

        # ── ukládání: idempotentní replace pod syntetickým scan zdrojem (pattern F1.2/F1.3) ──
        marker = f"{args.case_id}/antiforensics-scan"
        existing_src = next(
            (s for s in db.list_sources(args.case_id) if s.path == marker), None
        )
        scan_source = existing_src or EvidenceSource(
            case_id=args.case_id, kind="file", path=marker
        )
        if existing_src is None:
            db.add_source(scan_source)
        rec = FileRecord(
            source_id=scan_source.id, rel_path="antiforensics-scan.bin",
            name="antiforensics-scan.bin", size_bytes=0, signature_type="analysis",
        )
        scan_file_id = db.upsert_file(rec)

        sev_conf = {"high": 0.9, "medium": 0.7, "low": 0.5}
        now_dt = datetime.now(timezone.utc)
        arts: list[Artifact] = []
        for check in sorted(report["by_check"]):
            items = report["by_check"][check]
            for i, item in enumerate(items):
                ev = item.get("evidence") or {}
                ts_dt = now_dt
                ts_origin = "derived"
                raw_ts = ev.get("timestamp")
                if raw_ts:
                    try:
                        parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        ts_dt, ts_origin = parsed, "source"
                    except ValueError:
                        pass
                arts.append(Artifact(
                    source_id=scan_source.id, file_id=scan_file_id,
                    rel_path="antiforensics-scan.bin",
                    artifact_type=f"antiforensics/{check}",
                    title=item["description"][:160],
                    details={
                        "severity": item["severity"],
                        "risk_score": report["risk_score"],
                        **ev,
                    },
                    confidence=sev_conf.get(item["severity"], 0.5),
                    parser_version=af.PARSER_VERSION,
                    extracted_at=now_dt, timestamp=ts_dt, ts_origin=ts_origin,
                    anomaly_flags=[f"antiforensics:{check}"],
                ))
        # timeline alerty — idempotentní: scan zdroj je dedikovaný. Staré alerty
        # smažeme PŘED výměnou artifactů — odkazují na artefakty, které replace
        # maží, a FK timeline_events.artifact_id nemá ON DELETE (jinak porušení).
        db.clear_timeline_events(source_id=scan_source.id)
        db.replace_artifacts_for_file(scan_file_id, arts)
        for a in arts:
            check_name = a.artifact_type.split("/", 1)[1]
            db.add_timeline_event(
                source_id=scan_source.id, artifact_id=a.id, file_id=scan_file_id,
                rel_path="antiforensics-scan.bin",
                event_type=f"antiforensics_{check_name}",
                ts_utc=a.timestamp or now_dt, title=a.title, confidence=a.confidence,
                parser_version=af.PARSER_VERSION, extracted_at=now_dt,
                anomaly_flags=tuple(a.anomaly_flags), ts_origin=a.ts_origin,
            )
        db.commit()  # add_timeline_event nekonektuje commit — explicitně upevnit

        by_check_summary = {c: len(v) for c, v in report["by_check"].items()}
        if not json_mode:
            total = report["findings_count"]
            print()
            print(f"  Anti-forensics scan: {total} nálezů "
                  f"(risk score {report['risk_score']})")
            for check, n in sorted(by_check_summary.items()):
                print(f"    antiforensics/{check}: {n}")
            if not total:
                print("  — žádné stopy maskování důkazů nenalezeny ✓")
        if json_mode:
            _print_json({
                "case_id": args.case_id,
                **report,
                "artifacts_saved": len(arts),
                "files_scanned": len(files_norm),
                "events_scanned": len(events_norm),
                "usn_records_scanned": len(usn_norm),
                "stego_candidates": len(stego_paths),
            })
        return 0
    except Exception as e:  # noqa: BLE001 — analytická chyba ≠ pád CLI
        if json_mode:
            _print_json({"error": str(e)})
        else:
            print(f"Anti-forensics analýza selhala: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


