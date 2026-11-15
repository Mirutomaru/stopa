"""F3.2 — Triage profily (Ransomware, Insider Threat, CSAM/Média, Exfiltrace).

AK F3.2 (ROADMAP V2, Fáze 3):
- **4 profily** ✓ (``PROFILES`` má přesně 4 členy);
- každý profil detekuje **min. 8/10 syntetických pozitiv** → parametrizované
  testy s 10 recepturami na profil;
- **FPR < 5 %** na syntetických negativách → 10 „čistých" případů, FPR = FP/10
  (přísně < 5 % ⇒ 0 falešných pozitiv).

Receptury jsou deterministické — staví case DB přes facade + raw SQL stejně
jako ostatní suite (bez LLM, bez sítě).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from stopa.intelligence.triage import SignalSpec

CASE_ID = "case-f32"
SRC_ID = "src-f32"
TS_ART = datetime(2026, 1, 5, 12)  # deterministické razítko (bez utcnow → DTZ003)


# ── stavba case DB ────────────────────────────────────────────────


def _mk_file_rec(src_id: str, name: str):
    from stopa.models import FileRecord, new_id

    return FileRecord(
        id=new_id("f"),
        source_id=src_id,
        rel_path=name,
        name=name,
        size_bytes=2048,
        mtime=datetime(2026, 1, 1),
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        extension=name.rsplit(".", 1)[-1] if "." in name else "",
    )


class CaseBuilder:
    """Fluent seeder syntetických případů (soubory/artefakty/timeline/entity)."""

    def __init__(self, db) -> None:
        self.db = db
        self._n = 0

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def file(self, name: str) -> str:
        rec = _mk_file_rec(SRC_ID, name)
        self.db.upsert_file(rec)
        return rec.id

    def art(self, artifact_type: str, title: str = "", details: dict | None = None, rel_path: str | None = None) -> str:
        from stopa.models import Artifact

        a = Artifact(
            source_id=SRC_ID,
            artifact_type=artifact_type,
            timestamp=TS_ART,
            title=title,
            details=details or {},
            rel_path=rel_path,  # dedup klíč upsertu = (source_id, type, rel_path)
        )
        self.db.upsert_artifact(a)
        return a.id

    def tl(self, ts_utc: str = "2026-01-05T13:00:00+00:00", flags: str | None = None) -> str:
        ev_id = self._next("tl")
        self.db.conn.execute(
            "INSERT INTO timeline_events (id, source_id, artifact_id, file_id,"
            " rel_path, event_type, ts_utc, title, anomaly_flags)"
            " VALUES (?, ?, NULL, NULL, 'f32/notes.txt', 'browser_history', ?, 'tl', ?)",
            (ev_id, SRC_ID, ts_utc, flags),
        )
        self.db.conn.commit()
        return ev_id

    def entity(self, kind: str, value: str) -> None:
        self.db.upsert_entities(CASE_ID, [(kind, value, value, None, None)])


def _fresh_db(root: Path, tag: str):
    from stopa.data.db import CaseDB

    db = CaseDB(str(root / f"triage_{tag}.db"))
    now = "2026-01-01T00:00:00"
    db.conn.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)", (CASE_ID, CASE_ID.upper(), now))
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at) VALUES (?, ?, 'folder', '/tmp/f32-seed', ?)",
        (SRC_ID, CASE_ID, now),
    )
    db.conn.commit()
    return CaseBuilder(db)


# ── receptury SYNTETICKÝCH POZITIV (10 na profil; ≥8 musí být detekováno) ────


def _rs(b: CaseBuilder):  # ransomware
    b.art("antiforensics/timestomping", "bulk-touch 42 souborů")
    b.tl(flags="timestomp")
    b.file("docs/quarterly.locked")
    b.art("crypto_detection", "BTC wallet v poznámkách")


def _rn(b: CaseBuilder):
    b.file("RECOVERY_ME.txt")
    b.art("crypto_wallet", "WIF v dokumentu")


def _rc(b: CaseBuilder):
    b.file("photos/pic1.crypt")
    b.art("network/ioc", title="IoC c2_beaconing — pravidelný interval 30 s")


def _rt_only(b: CaseBuilder):  # hranice: jen timestomp (1 signál, skóre 2 < 3)
    b.art("antiforensics/timestomping", "future mtime")


def _rfn(b: CaseBuilder):  # hranice: flag + note (skóre 2 < 3)
    b.tl(flags="timestomp")
    b.file("docs/readme.html")


def _rexw(b: CaseBuilder):
    b.file("backup.wcry")
    b.art("crypto_wallet", "ETH address v ransom notě")


def _rtc2(b: CaseBuilder):
    b.art("antiforensics/timestomping", "M<C pořad")
    b.tl(flags="timestomp")
    b.art("network/ioc", title="IoC c2_beaconing")


def _rnote_ext(b: CaseBuilder):
    b.file("restore_me.txt")
    b.file("data.crypt")


def _rw2c2(b: CaseBuilder):
    b.art("crypto_detection", "seed phrase v clipboardu")
    b.art("crypto_wallet", "WIF")
    b.art("network/ioc", title="IoC c2_beaconing")


def _rfull3(b: CaseBuilder):
    b.file("img.locked")
    b.file("recovery_me.txt")
    b.art("network/ioc", details={"rule": "c2_beaconing"})


RANSOMWARE_POS = [_rs, _rn, _rc, _rt_only, _rfn, _rexw, _rtc2, _rnote_ext, _rw2c2, _rfull3]


def _iu1(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "delete ratio 0.85")
    b.art("drive_activity", title="USB E: připojeno")


def _iu2(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "USN truncation")
    b.art("antiforensics/timestomping", "bulk-touch 12 souborů")


def _iu3(b: CaseBuilder):
    b.art("drive_activity", title="USB F: odpojeno")
    b.entity("email", "john.carter@gmail.com")


def _iu4(b: CaseBuilder):  # hranice: jen USN (1 signál)
    b.art("antiforensics/usn_truncation", "delete ratio 0.6")


def _iu5(b: CaseBuilder):  # hranice: osobní schránka + timestomp (skóre 2 < 3)
    b.entity("email", "sara.k@yahoo.com")
    b.art("antiforensics/timestomping", "future mtime")


def _iu6(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "delete ratio 0.9")
    b.art("drive_activity", title="USB G:")
    b.entity("email", "dave.b@outlook.com")


def _iu7(b: CaseBuilder):
    b.art("antiforensics/timestomping", "nemožný pořad M<C")
    b.art("drive_activity", title="ODD D:")


def _iu8(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "delete ratio 0.7")
    b.art("antiforensics/usn_truncation", "journal truncated")
    b.art("drive_activity", title="USB H:")


def _iu9(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "delete ratio 0.55")
    b.entity("email", "mia@outlook.com")


def _iu10(b: CaseBuilder):
    b.art("antiforensics/usn_truncation", "x")
    b.art("antiforensics/timestomping", "y")
    b.art("drive_activity", title="USB I:")
    b.entity("email", "leo@gmail.com")


INSIDER_POS = [_iu1, _iu2, _iu3, _iu4, _iu5, _iu6, _iu7, _iu8, _iu9, _iu10]


def _im(b: CaseBuilder, n_img: int):
    for i in range(n_img):
        b.file(f"media/img_{i}.jpg")


def _c1(b: CaseBuilder):
    b.art("antiforensics/steganography", "LSB v PNG")
    _im(b, 6)


def _c2(b: CaseBuilder):
    b.art("antiforensics/steganography", "bitová vyváženost")
    b.art("voice_recording", title="Nahrávka 0345.wav")


def _c3(b: CaseBuilder):
    _im(b, 8)
    b.art("antiforensics/hidden_partition", "skrytá partice")


def _c4(b: CaseBuilder):  # hranice: jen stego (1 signál)
    b.art("antiforensics/steganography", "Shannon entropie")


def _c5(b: CaseBuilder):  # hranice: audio + hidden part (skóre 2 < 3)
    b.art("voice_recording", title="a.wav")
    b.art("antiforensics/hidden_partition", "MBR anomálie")


def _c6(b: CaseBuilder):
    b.art("antiforensics/steganography", "x")
    _im(b, 5)


def _c7(b: CaseBuilder):
    _im(b, 6)
    b.art("antiforensics/hidden_partition", "y")


def _c8(b: CaseBuilder):
    b.art("antiforensics/steganography", "z")
    b.art("voice_recording", title="b.wav")
    _im(b, 5)


def _c9(b: CaseBuilder):
    _im(b, 6)
    b.art("voice_recording", title="c.wav")


def _c10(b: CaseBuilder):
    b.art("antiforensics/steganography", "s1")
    b.art("antiforensics/steganography", "s2")
    b.art("antiforensics/hidden_partition", "p")


CSAM_POS = [_c1, _c2, _c3, _c4, _c5, _c6, _c7, _c8, _c9, _c10]


def _e_blob(b: CaseBuilder):
    b.art("network/ioc", title="IoC base64_blob_payload — 2.1 MB")


def _att(b: CaseBuilder, n: int):
    for i in range(n):
        b.art("email_attachment", title=f"attachment_{i}.zip", rel_path=f"mail/inbox/{i}.eml")


def _cloud(b: CaseBuilder, n: int):
    for i in range(n):
        b.art("cloud_file", title=f"upload_{i}", rel_path=f"cloud/share/doc_{i}")


def _x1(b: CaseBuilder):
    _e_blob(b)
    _att(b, 3)


def _x2(b: CaseBuilder):
    _att(b, 4)
    _cloud(b, 6)


def _x3(b: CaseBuilder):
    _e_blob(b)
    b.art("antiforensics/usn_truncation", "delete po uploadu")


def _x4(b: CaseBuilder):  # hranice: jen 3 přílohy (1 signál, skóre 2 < 3)
    _att(b, 3)


def _x5(b: CaseBuilder):  # hranice: jen cloud 6 (skóre 1 < 3)
    _cloud(b, 6)


def _x6(b: CaseBuilder):
    _e_blob(b)
    _att(b, 3)
    b.art("antiforensics/usn_truncation", "y")


def _x7(b: CaseBuilder):
    _e_blob(b)
    _cloud(b, 6)


def _x8(b: CaseBuilder):
    _att(b, 3)
    b.art("antiforensics/usn_truncation", "z")


def _x9(b: CaseBuilder):
    _att(b, 5)
    _cloud(b, 6)


def _x10(b: CaseBuilder):
    _e_blob(b)
    _att(b, 4)
    _cloud(b, 6)
    b.art("antiforensics/usn_truncation", "w")


EXFIL_POS = [_x1, _x2, _x3, _x4, _x5, _x6, _x7, _x8, _x9, _x10]


# ── čistý negativní případ (normální kancelářský uživatel) ───────────────────


def _clean(b: CaseBuilder):
    # 3 obrázky (< min_count 5 image_cluster), běžné dokumenty
    for i in range(3):
        b.file(f"pics/holiday_{i}.jpg")
    b.file("docs/readme.txt")
    b.file("docs/report.pdf")
    # běžná aktivita — žádné forenzní markery
    b.art("browser_history", title="www.ceska-posta.cz")
    b.art("email_message", title="Re: Schůzka ve čtvrtek")
    b.art("chat_message", title="OK, posílám soubor")
    _cloud(b, 2)
    # pracovní (ne osobní) schránka → personal_mailbox nespálí
    b.entity("email", "jane.doe@example.com")


# ── testy AK ───────────────────────────────────────────────────────


PROFILE_RECIPES = {
    "ransomware": RANSOMWARE_POS,
    "insider_threat": INSIDER_POS,
    "csam_media": CSAM_POS,
    "exfiltration": EXFIL_POS,
}


@pytest.mark.parametrize("profile_key", sorted(PROFILE_RECIPES))
def test_ak_detection_min_8_of_10(profile_key: str, tmp_path: Path):
    """AK F3.2: každý profil detekuje min. 8/10 syntetických pozitiv."""
    from stopa.intelligence.triage import evaluate_profile, get_profile

    profile = get_profile(profile_key)
    detected = 0
    for i, recipe in enumerate(PROFILE_RECIPES[profile_key]):
        b = _fresh_db(tmp_path / f"pos_{i}", profile_key[:3] + str(i))
        recipe(b)
        report = evaluate_profile(b.db, CASE_ID, profile)
        if report.detected:
            detected += 1
    assert detected >= 8, (
        f"{profile_key}: detekováno {detected}/10 pozitiv "
        f"(očekáváno ≥8); skóre viz receptury"
    )


@pytest.mark.parametrize("profile_key", sorted(PROFILE_RECIPES))
def test_ak_fpr_under_5_percent(profile_key: str, tmp_path: Path):
    """AK F3.2: FPR < 5 % na syntetických negativách (10 čistých případů)."""
    from stopa.intelligence.triage import evaluate_profile, get_profile

    profile = get_profile(profile_key)
    false_positives = 0
    for i in range(10):
        b = _fresh_db(tmp_path / f"neg_{i}", "neg")
        _clean(b)
        report = evaluate_profile(b.db, CASE_ID, profile)
        if report.detected:
            false_positives += 1
    assert false_positives < 0.05 * 10, (
        f"{profile_key}: FPR {false_positives}/10 ≥ 5 %"
    )


# ── unit testy engine ───────────────────────────────────────────────


class TestTriageEngine:
    def test_profiles_count_and_keys(self):
        """AK F3.2: přesně 4 profily s definovanými klíči."""
        from stopa.intelligence.triage import PROFILES

        assert len(PROFILES) == 4
        assert {p.key for p in PROFILES} == {"ransomware", "insider_threat", "csam_media", "exfiltration"}
        for p in PROFILES:
            assert all(s.weight > 0 for s in p.signals), f"{p.key}: váhy musí být > 0"

    def test_min_signals_gate(self):
        """FPR guard: dosažení prahu JEDNÍM signálem nestačí (min. 2 různé)."""
        from stopa.intelligence.triage import MatchedSignal, ProfileReport, TriageProfile

        spec = SignalSpec(key="solo", weight=5, kind="artifact_type", patterns=("x",))
        profile = TriageProfile(
            key="t", title="T", description="", signals=(spec,), threshold=3, min_signals=2
        )
        one = ProfileReport(profile=profile, matched=(MatchedSignal(spec, 10, ("a",)),), score=5)
        assert not one.detected, "jeden signál nad prahem → stále nedetekováno (min_signals)"
        spec2 = SignalSpec(key="second", weight=1, kind="artifact_type", patterns=("y",))
        profile2 = TriageProfile(
            key="t2", title="T", description="", signals=(spec, spec2), threshold=3, min_signals=2
        )
        two = ProfileReport(profile=profile2, matched=(MatchedSignal(spec, 10, ()), MatchedSignal(spec2, 1, ("b",))), score=6)
        assert two.detected

    def test_hypothesis_rendering(self):
        """Hypotéza template se plní case_id/skóre/signály."""
        from stopa.intelligence.triage import RANSOMWARE, ProfileReport

        report = ProfileReport(profile=RANSOMWARE, matched=(), score=0)
        text = report.hypothesis("case-xyz")
        assert "case-xyz" in text and "žádné signály" in text
        assert "{case_id}" not in text  # žádné nevyplněné sloty

    def test_run_triage_ordering_and_unknown_key(self, tmp_path: Path):
        """run_triage řadí dle skóre sestupně; get_profile zná ValueError."""
        from stopa.intelligence.triage import get_profile, run_triage

        b = _fresh_db(tmp_path, "ord")
        # ransomware receptura → ransomware report musí být první (max skóre)
        RANSOMWARE_POS[0](b)
        reports = run_triage(b.db, CASE_ID)
        assert len(reports) == 4
        assert reports[0].profile.key == "ransomware"
        scores = [r.score for r in reports]
        assert scores == sorted(scores, reverse=True)

        with pytest.raises(ValueError):
            get_profile("neexistujici")

    def test_min_count_file_cluster(self, tmp_path: Path):
        """file_pattern s min_count=5 nespálí při 3 obrázcích (FPR kontrola)."""
        from stopa.intelligence.triage import CSAM_MEDIA, evaluate_profile

        b = _fresh_db(tmp_path, "mc")
        for i in range(3):
            b.file(f"m/pic_{i}.png")
        report = evaluate_profile(b.db, CASE_ID, CSAM_MEDIA)
        keys = {m.spec.key for m in report.matched}
        assert "image_cluster" not in keys
        assert not report.detected

    def test_empty_case_no_detections(self, tmp_path: Path):
        """Prázdný case → skóre 0 ve všech profilech."""
        from stopa.intelligence.triage import run_triage

        b = _fresh_db(tmp_path, "empty")
        reports = run_triage(b.db, CASE_ID)
        assert all(r.score == 0 and not r.detected for r in reports)
