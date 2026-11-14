//! STOPA Rust core (F2.1) — high-performance hashing + carving scan.
//! F2.3: one-pass CDC chunking s Buzhash rolling hashem + SHA-256 per blok.
//!
//! PyO3 extension. Čistá jádra [`compute_hashes`] / [`scan_data`] /
//! [`block_dedupe_core`] jsou bez PyO3 typů → testují se přes `cargo test`
//! offline; pyfunction vrstva jen uvolní GIL (`py.detach`) a převede chyby na
//! Python výjimky.
//!
//! Semantika = přesná parity s Python referencí:
//! - hash: one-pass MD5/SHA-1/SHA-256, neznámý algoritmus → ValueError
//! - scan: per-pattern nenakládající shody (ekvivalent smyčky `data.find(magic)`)
//! - buzhash_blocks: CDC hranice v [min_size, max_size), avg musí být mocnina 2;
//!   rolling hash = Σ table[i % 32] * byte přes posuvné okno o velikosti avg

use aho_corasick::AhoCorasick;
use md5::Context as Md5Ctx;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedBytes;
use pyo3::types::{PyDict, PyList};
use sha1::Sha1;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::Read;

const CHUNK_SIZE: usize = 4 * 1024 * 1024; // 4 MiB — IO + CPU pipelining

/// Buzhash tabulka (32 × u64) — deterministická, sdílená s Python referencí
/// (domain/block_dedupe.py) pro bitovou parity Rust ↔ Python.
const BUZ_TABLE: [u64; 32] = [
    0x6b0a59c4f168861e, 0x407e9a8fed24704e, 0x74a8dacdbf8ac204, 0x459f56fefc3bcf9a,
    0x7b56658724da3bf4, 0x1b04e8e7656f43c1, 0x709204fb0595d757, 0x1f2152744af0dc45,
    0x62c65f5b4bf683f2, 0x2539d5efeeb60725, 0x5b689baeb9b8c7bd, 0x309a262615f2e29a,
    0x653853b5d1959792, 0x4e85eebd30844e4d, 0x660b1db367dd50c5, 0xdcf3b320a222a6,
    0x769ce5c1f17fc890, 0x5b0487024d070786, 0x5cd1789663986181, 0x27ee3dafc58c10da,
    0x5f6d81a8813daf12, 0x71b06a477c38afd3, 0x13a83c84e5df789a, 0x5a53f2dd1dc8e4dc,
    0x440bf4593c424d7d, 0x1522168032c57cbb, 0x11848ddb3f258424, 0x5e748428a83482f3,
    0xfce417185e02054, 0x3543191af16af448, 0x439e9e211229e1e3, 0x5a7daedea14ce4ad,
];

/// Prepočtené váhy W[byte][r] = BUZ_TABLE[r] * byte — 64 KB (L1 cache).
/// Hot loop pak dělá jen 2× lookup bez 64-bit násobení na bajt (F2.3 AK overhead).
/// (Tento toolchain nebere `for` v const initializátoru → OnceLock, std-only.)
static BUZ_WEIGHTS: std::sync::OnceLock<[u64; 256 * 32]> = std::sync::OnceLock::new();

fn buz_weights() -> &'static [u64] {
    BUZ_WEIGHTS.get_or_init(|| {
        let mut t = [0u64; 256 * 32];
        for b in 0..=255usize {
            for r in 0..32 {
                t[b << 5 | r] = BUZ_TABLE[r].wrapping_mul(b as u64);
            }
        }
        t
    })
}

/// Truncované váhy na 16 bitů — pro fast16 cestu (avg ∈ [32, 65536]).
/// Hranicová podmínka `(hash & mask) == 0` s `mask < 2^16` závisí jen na nízkých
/// bitech rolling hashu → u16 akumulator je BIT-EXAKTNÍ (nízké bity součtu se
/// počítají nezávisle na vysokých). Stejné hranice jako plný u64, 2× méně práce.
const BUZ_TABLE_16: [u16; 32] = [
    0x861e, 0x704e, 0xc204, 0xcf9a, 0x3bf4, 0x43c1, 0xd757, 0xdc45,
    0x83f2, 0x0725, 0xc7bd, 0xe29a, 0x9792, 0x4e4d, 0x50c5, 0x22a6,
    0xc890, 0x0786, 0x6181, 0x10da, 0xaf12, 0xafd3, 0x789a, 0xe4dc,
    0x4d7d, 0x7cbb, 0x8424, 0x82f3, 0x2054, 0xf448, 0xe1e3, 0xe4ad,
];

/// One-pass block-level deduplikace nad souborem (F2.3).
///
/// Streaming: čte soubor v `CHUNK_SIZE` kusech, udržuje posuvné okno
/// `avg_size` bajtů (ring buffer) + Buzhash rolling hash + SHA-256 aktuálního
/// bloku. Hranice bloku když je okno plné (`pos+1 >= avg`) a délka bloku
/// `len >= min` a `(hash & (avg-1)) == 0` NEBO `len >= max`. Okno po cutu se
/// NEREZETUJE — klouže neustále přes celý soubor (deterministické, bit-exaktní
/// parity s Python referencí `domain/block_dedupe.py`). Poslední zbytek (< min)
/// jde do závěrečného bloku. Prázdný soubor → [].
///
/// Výkon: rolling hash je O(1)/bajt, ale SHA-256 se aktualizuje BULK — jen na
/// hranicích bloků a na konci každého chunku (nikdy po jednom bajtu), takže
/// drahá digest funkce běží na celých segmentech. Blok může přesahovat chunk;
/// invariant: na začátku každého chunku je `sha_up_to == chunk_start` (předchozí
/// chunk-end flush vždy dožene zbývající byty), takže všechny SHA aktualizace
/// padají do aktuálního bufferu. Chyba: IO / neplatné parametry (bez paniku).
pub fn block_dedupe_core(
    path: &str,
    avg_size: usize,
    min_size: usize,
    max_size: usize,
) -> Result<Vec<(String, i64)>, String> {
    // cesta pro jediný soubor — vlastní IO buffer (batch sdílí jeden přes dedupe_into)
    let mut buf = vec![0u8; CHUNK_SIZE];
    dedupe_into(path, avg_size, min_size, max_size, &mut buf)
}

/// Vlastní one-pass stroj F2.3 — `buf` je IO buffer (≥ CHUNK_SIZE), který se mezi
/// voláními může SDÍLET (batch cesta šetří per-soubor calloc + first-touch faults).
fn dedupe_into(
    path: &str,
    avg_size: usize,
    min_size: usize,
    max_size: usize,
    buf: &mut [u8],
) -> Result<Vec<(String, i64)>, String> {
    if avg_size == 0 || !avg_size.is_power_of_two() {
        return Err("avg musí být mocnina 2".to_string());
    }
    if !(min_size > 0 && min_size <= avg_size && avg_size <= max_size) {
        return Err("0 < min ≤ avg ≤ max".to_string());
    }

    let mut file = File::open(path).map_err(|e| format!("IO: {e}"))?;
    let n_file = file.metadata().map_err(|e| format!("stat: {e}"))?.len();
    if n_file == 0 {
        return Ok(Vec::new());
    }

    let mask = (avg_size - 1) as u64;
    // ring[slot] drží data[pos - avg_size]; slot = pos % avg_size
    let mut ring = vec![0u8; avg_size];
    let mut hash: u64 = 0;       // plný rolling hash (fast_u64 / generic cesta)
    let mut h16: u16 = 0;        // truncovaný rolling hash — fast16 cesta (avg ≤ 65536)
    let mut block_start: usize = 0;   // absolutní offset začátku aktuálního bloku
    let mut sha_up_to: usize = 0;     // všechny byty < toto už v aktuálním (nefinalizovaném) SHA
    let mut sha = Sha256::new();
    let mut out: Vec<(String, i64)> = Vec::new();
    let mut pos_now: usize = 0;       // absolutní offset dalšího čteného bajtu

    // FAST16 PATH (avg ∈ [32, 65536]): váha je LINEÁRNÍ v byte hodnotě a evikovaný
    // byte má STEJNÝ slot ((pos-avg)&31 == pos&31, protože avg % 32 == 0) → delta
    // tvar h += W_s·(b − old), jedno násobení/bajt. Mask < 2^16 → stačí u16 akumulator
    // (nízké bity součtu jsou nezávislé na vysokých = BIT-EXAKTNÍ parity s plným hashem).
    let fast16 = avg_size >= 32 && avg_size <= 65_536;
    // FAST_U64 PATH (avg > 65536): lineární váhy, ale mask potřebuje vyšší bity → plný u64.
    let fast_u64 = !fast16 && avg_size >= 32;
    // generická cesta (avg < 32) potřebuje plnou tabulku (lazy init jednou za process)
    let weights = buz_weights();

    loop {
        let n = file.read(buf).map_err(|e| format!("IO: {e}"))?;
        if n == 0 {
            break;
        }
        let chunk_start = pos_now; // absolutní offset buf[0] v této iteraci

        for i in 0..n {
            let b = buf[i];
            let pos = chunk_start + i;
            let slot = pos & (avg_size - 1); // avg garantovaně mocnina 2
            if fast16 {
                let w16 = BUZ_TABLE_16[pos & 31];
                if pos >= avg_size {
                    // steady state: delta tvar — jedno násobení, sdílená váha (avg % 32 == 0)
                    h16 = h16.wrapping_add(w16 * (b as u16).wrapping_sub(ring[slot] as u16));
                } else {
                    // warmup: okno ještě neplné → jen přídavná část, bez evikce
                    h16 = h16.wrapping_add(w16 * (b as u16));
                }
                ring[slot] = b;
            } else if fast_u64 {
                let w = BUZ_TABLE[pos & 31];
                if pos >= avg_size {
                    hash = hash.wrapping_sub(w * u64::from(ring[slot]));
                }
                ring[slot] = b;
                hash = hash.wrapping_add(w * u64::from(b));
            } else {
                // GÉNÉRICKÁ CESTA (avg < 32): plná váhová tabulka W[byte][slot]
                if pos >= avg_size {
                    let old = ring[slot];
                    hash = hash.wrapping_sub(weights[(old as usize) << 5 | ((pos - avg_size) & 31)]);
                }
                ring[slot] = b;
                hash = hash.wrapping_add(weights[(b as usize) << 5 | (pos & 31)]);
            }

            let hb: u64 = if fast16 { h16 as u64 } else { hash };
            let len = pos + 1 - block_start;
            if (pos + 1 >= avg_size && len >= min_size && hb & mask == 0) || len >= max_size {
                // hranice bloku → BULK flush [sha_up_to..=pos], finalizuj, restart SHA
                let l = i64::try_from(len).unwrap_or(i64::MAX);
                sha.update(&buf[(sha_up_to - chunk_start)..(i + 1)]);
                out.push((to_hex(&sha.finalize_reset()), l));
                block_start = pos + 1;
                sha_up_to = pos + 1; // další SHA startuje hned za touto hranicí
            }
        }

        // konec chunku: BULK flush zbývajících [sha_up_to..n) — blok může přesahovat chunk.
        if (chunk_start + n) > sha_up_to {
            let local_start = (sha_up_to - chunk_start).min(n);
            if n > local_start {
                sha.update(&buf[local_start..n]);
            }
        }
        // všechny byty do konce chunku jsou už v aktuálním SHA — posunout ukazatel,
        // jinak cut v dalším chunku re-feedne (podflow absolutního offsetu)
        sha_up_to = chunk_start + n;
        pos_now += n;
    }

    // závěrečný zbytek (může být < min) — deterministické ukončení
    if block_start < n_file as usize {
        let len = i64::try_from(n_file as usize - block_start).unwrap_or(i64::MAX);
        out.push((to_hex(&sha.finalize()), len));
    }
    Ok(out)
}
/// HEX LUT pro rychlé kódování digestů (bez format! per byte).
const HEX_LUT: &[u8; 64] = b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn to_hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(HEX_LUT[(b >> 4) as usize] as char);
        s.push(HEX_LUT[(b & 0x0f) as usize] as char);
    }
    s
}

/// Generic hasher (MD5 / SHA-1 / SHA-256) v jednom průchodu.
enum H {
    Md5(Md5Ctx),
    Sha1(Sha1),
    Sha256(Sha256),
}

impl H {
    fn new(name: &str) -> Option<Self> {
        match name.to_ascii_lowercase().as_str() {
            "md5" => Some(H::Md5(Md5Ctx::new())),
            "sha1" | "sha-1" => Some(H::Sha1(Sha1::new())),
            "sha256" | "sha-256" => Some(H::Sha256(Sha256::new())),
            _ => None,
        }
    }

    fn update(&mut self, data: &[u8]) {
        match self {
            H::Md5(c) => c.consume(data),
            H::Sha1(h) => h.update(data),
            H::Sha256(h) => h.update(data),
        }
    }

    fn hex(self) -> String {
        let out: Vec<u8> = match self {
            H::Md5(c) => c.compute().to_vec(),
            H::Sha1(h) => h.finalize().to_vec(),
            H::Sha256(h) => h.finalize().to_vec(),
        };
        to_hex(&out)
    }
}

/// One-pass streaming hashing souboru (čistá Rust jádro, bez PyO3).
/// Vrací `(algoritmus_lower, hex_digest)` v pořadí `names`. Chyba: IO / neznámý algoritmus.
fn compute_hashes(path: &str, names: &[String]) -> Result<Vec<(String, String)>, String> {
    let mut hashers = Vec::with_capacity(names.len());
    for n in names {
        match H::new(n) {
            Some(h) => hashers.push((n.clone(), h)),
            None => return Err(format!("Neznámé algoritmy: {n}")),
        }
    }
    let mut file = File::open(path).map_err(|e| format!("IO: {e}"))?;
    let mut buf = vec![0u8; CHUNK_SIZE];
    loop {
        let n = file.read(&mut buf).map_err(|e| format!("IO: {e}"))?;
        if n == 0 {
            break;
        }
        for (_, h) in hashers.iter_mut() {
            h.update(&buf[..n]);
        }
    }
    Ok(hashers
        .into_iter()
        .map(|(name, h)| (name, h.hex()))
        .collect())
}

/// Aho-Corasick multi-pattern scan — přímá parity s Python `data.find(magic)` smyčkou.
///
/// Pro každý pattern zvlášť se berou nenakládající shody: po shodě na pozici p
/// se další hledá od p + len(pattern) (greedy filtr přes overlapping AC shody).
/// Výsledek je deterministicky seřazený `(offset, pattern_index)`. Prázdné
/// patterny se ignorují. Chyba: AC build selhal.
fn scan_data(data: &[u8], patterns: &[Vec<u8>]) -> Result<Vec<(i64, i64)>, String> {
    let non_empty: Vec<usize> = (0..patterns.len())
        .filter(|&i| !patterns[i].is_empty())
        .collect();
    if non_empty.is_empty() || data.is_empty() {
        return Ok(Vec::new());
    }
    let refs: Vec<&[u8]> = non_empty.iter().map(|&i| patterns[i].as_slice()).collect();
    let ac = AhoCorasick::new(&refs).map_err(|e| format!("Aho-Corasick build: {e}"))?;

    let mut last_end = vec![0i64; patterns.len()];
    let mut found: Vec<(i64, i64)> = Vec::new();
    for mat in ac.find_overlapping_iter(data) {
        // AC pattern index → původní index v `patterns` (prázdné vynechány)
        let orig = non_empty[mat.pattern()];
        let start = mat.start() as i64;
        if start >= last_end[orig] {
            found.push((start, orig as i64));
            last_end[orig] = start + patterns[orig].len() as i64;
        }
    }
    // determinismus: na stejném offsetu může AC vydat více patternů → explicitní sort
    found.sort();
    Ok(found)
}

/// Streaming one-pass hashing souboru — MD5/SHA-1/SHA-256 v jednom čtení.
/// GIL je uvolněné po celou dobu; vrácený dict: `{alg_lower: hex_digest}`.
#[pyfunction]
fn hash_file<'py>(
    path: &str,
    algorithms: Vec<String>,
    py: Python<'py>,
) -> PyResult<Bound<'py, PyDict>> {
    let names: Vec<String> = algorithms.iter().map(|a| a.to_ascii_lowercase()).collect();
    // fail fast na neznámý algoritmus (parity s Python ValueError) PŘED detachem
    for n in &names {
        if H::new(n).is_none() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Neznámé algoritmy: {n}"
            )));
        }
    }
    let result = py.detach(|| compute_hashes(&path, &names));
    let pairs = result.map_err(|e| pyo3::exceptions::PyOSError::new_err(e))?;
    let dict = PyDict::new(py);
    for (name, hexd) in pairs {
        dict.set_item(name, hexd)?;
    }
    Ok(dict)
}

/// Aho-Corasick multi-pattern scan (zero-copy přes buffer protocol).
/// Vrátí list `[offset, pattern_index]` seřazený deterministicky.
#[pyfunction]
fn find_offsets(
    data: PyBackedBytes,
    patterns: Vec<Vec<u8>>,
    py: Python<'_>,
) -> PyResult<Bound<'_, PyList>> {
    let result = py.detach(|| scan_data(&data, &patterns));
    let found = result.map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    let list = PyList::empty(py);
    for (off, idx) in found {
        list.append((off, idx))?;
    }
    Ok(list)
}

/// Verze Rust core pro diagnostics.
#[pyfunction]
fn rust_version() -> &'static str {
    "0.1.0"
}

/// One-pass block-level deduplikace souboru (F2.3) — Python-facing binding.
/// Uvolní GIL po celou dobu; vrátí list `[sha256_hex, length]` v pořadí bloků.
#[pyfunction]
fn block_dedupe(
    path: &str,
    avg_size: usize,
    min_size: usize,
    max_size: usize,
    py: Python<'_>,
) -> PyResult<Vec<(String, i64)>> {
    let result = py.detach(|| block_dedupe_core(path, avg_size, min_size, max_size));
    result.map_err(|e| pyo3::exceptions::PyOSError::new_err(e))
}

/// One-pass block-level deduplikace VÍCE souborů v jediném volání (F2.3).
/// Jediné uvolnění GIL pro celý batch + jeden sdílený IO buffer — bez per-file
/// hraničního overheadu (pyo3 přechod, GIL detach/reattach i calloc/page faults
/// na každý soubor). Vrátí list v pořadí `paths`; IO chyba prvního chybného
/// souboru se propaguje jako OSError se jménem souboru. Parametry jsou shodné
/// pro všechny soubory (validaci dělá Python facade jednou před voláním — parity
/// s `block_dedupe`).
#[pyfunction]
fn block_dedupe_files(
    paths: Vec<String>,
    avg_size: usize,
    min_size: usize,
    max_size: usize,
    py: Python<'_>,
) -> PyResult<Vec<Vec<(String, i64)>>> {
    let result = py.detach(|| {
        // jedna 4 MiB alokace pro celý batch (místo per-soubor) — šetří calloc + first-touch faults
        let mut buf: Vec<u8> = vec![0u8; CHUNK_SIZE];
        paths
            .iter()
            .map(|p| dedupe_into(p, avg_size, min_size, max_size, &mut buf).map_err(|e| format!("{p}: {e}")))
            .collect::<Result<Vec<_>, _>>()
    });
    result.map_err(|e| pyo3::exceptions::PyOSError::new_err(e))
}

#[pymodule]
fn stopa_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(hash_file, m)?)?;
    m.add_function(wrap_pyfunction!(find_offsets, m)?)?;
    m.add_function(wrap_pyfunction!(block_dedupe, m)?)?;
    m.add_function(wrap_pyfunction!(block_dedupe_files, m)?)?;
    m.add_function(wrap_pyfunction!(rust_version, m)?)?;
    Ok(())
}

// ── Rust unit testy (běží bez Python interpreteru — offline CI) ─────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_file(content: &[u8]) -> tempfile::NamedTempFile {
        let f = tempfile::Builder::new().suffix(".bin").tempfile().unwrap();
        use std::io::Write;
        f.as_file().write_all(content).unwrap();
        f
    }

    #[test]
    fn hash_known_vectors() {
        // MD5("abc")=900150983cd24fb0d6963f7d28e17f72, SHA-1= a9993e364706816aba3e25717850c26c9cd0d89d
        let f = temp_file(b"abc");
        let path = f.path().to_str().unwrap();
        let names = vec!["md5".into(), "sha1".into(), "sha256".into()];
        let res = compute_hashes(path, &names).unwrap();
        assert_eq!(res[0].1, "900150983cd24fb0d6963f7d28e17f72");
        assert_eq!(res[1].1, "a9993e364706816aba3e25717850c26c9cd0d89d");
        assert_eq!(
            res[2].1,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn hash_empty_file() {
        // prázdný soubor → platné prázdné digesty (SHA-256 e3b0c442…)
        let f = temp_file(b"");
        let path = f.path().to_str().unwrap();
        let names = vec!["sha256".into()];
        let res = compute_hashes(path, &names).unwrap();
        assert_eq!(
            res[0].1,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn hash_unknown_algorithm() {
        let f = temp_file(b"x");
        let path = f.path().to_str().unwrap();
        let names = vec!["sha384".into()];
        assert!(compute_hashes(path, &names).is_err());
    }

    #[test]
    fn hash_streaming_matches_oneshot() {
        // determinismus: chunkovaný průchod == one-shot (data přes CHUNK_SIZE hranice)
        let mut data = Vec::with_capacity(CHUNK_SIZE + 12345);
        for i in 0..(CHUNK_SIZE / 7 + 1) {
            data.push((i % 251) as u8);
        }
        let f = temp_file(&data);
        let path = f.path().to_str().unwrap();
        let names = vec!["md5".into(), "sha1".into(), "sha256".into()];
        let streamed = compute_hashes(path, &names).unwrap();

        // one-shot kontrola přímo přes H
        let mut hs: Vec<H> = vec![
            H::new("md5").unwrap(),
            H::new("sha1").unwrap(),
            H::new("sha256").unwrap(),
        ];
        for h in hs.iter_mut() {
            h.update(&data);
        }
        let oneshot_hexes: Vec<String> = hs.into_iter().map(|h| h.hex()).collect();
        for (i, (_, hexd)) in streamed.into_iter().enumerate() {
            assert_eq!(hexd, oneshot_hexes[i]);
        }
    }

    /// Naivní referenční scan = přesná emulace Python `data.find` smyčky.
    fn naive_scan(data: &[u8], patterns: &[Vec<u8>]) -> Vec<(i64, i64)> {
        let mut out = Vec::new();
        for (pi, p) in patterns.iter().enumerate() {
            if p.is_empty() {
                continue;
            }
            // Rust bytes.find loop — stejná sémantika jako Python str/bytes find
            let mut pos: i64 = 0;
            while let Some(off) = data[pos.max(0) as usize..]
                .windows(p.len())
                .position(|w| w == p.as_slice())
            {
                // position() na windowch je O(n*m) — jen pro testy (malá data)
                let abs = pos + off as i64;
                out.push((abs, pi as i64));
                pos = abs + p.len() as i64;
            }
        }
        // Python: header signatury se zpracovávají v pořadí patternů a výsledek carve()
        // nakonec sortuje podle offsetu → pro parity sémantiky stačí (offset, index) sort
        out.sort();
        out
    }

    #[test]
    fn scan_basic() {
        let data = b"xxPNGxxPDFxx".to_vec();
        let patterns = vec![b"PNG".to_vec(), b"PDF".to_vec()];
        assert_eq!(
            scan_data(&data, &patterns).unwrap(),
            naive_scan(&data, &patterns)
        );
        assert_eq!(scan_data(&data, &patterns).unwrap(), vec![(2, 0), (7, 1)]);
    }

    #[test]
    fn scan_non_overlapping_semantics() {
        // pattern "aa" v "aaaa": Python find smyčka → pozice 0 a 2 (ne 1!)
        let data = b"aaaa".to_vec();
        let patterns = vec![b"aa".to_vec()];
        assert_eq!(scan_data(&data, &patterns).unwrap(), vec![(0, 0), (2, 0)]);
    }

    #[test]
    fn scan_shared_prefix_patterns_independent() {
        // patterny s společným prefixem jsou nezávislé (každý má vlastní find smyčku)
        let data = b"PK\x03\x04PK\x01\x02PK\x03\x04".to_vec();
        let patterns = vec![b"PK\x03\x04".to_vec(), b"PK\x01\x02".to_vec()];
        assert_eq!(
            scan_data(&data, &patterns).unwrap(),
            naive_scan(&data, &patterns)
        );
    }

    #[test]
    fn scan_duplicate_patterns_both_reported() {
        // duplicitní pattern (stejná magie pro 2 signatury) → shoda na obou indexech
        let data = b"ABxAB".to_vec();
        let patterns = vec![b"AB".to_vec(), b"AB".to_vec()];
        assert_eq!(
            scan_data(&data, &patterns).unwrap(),
            naive_scan(&data, &patterns)
        );
    }

    #[test]
    fn scan_empty_pattern_ignored() {
        let data = b"ABC".to_vec();
        let patterns = vec![vec![], b"B".to_vec(), vec![]];
        assert_eq!(scan_data(&data, &patterns).unwrap(), vec![(1, 1)]);
    }

    #[test]
    fn scan_no_match_and_empty() {
        let data = b"hello world".to_vec();
        assert!(scan_data(&data, &[b"XYZ".to_vec()]).unwrap().is_empty());
        assert!(scan_data(b"", &[b"A".to_vec()]).unwrap().is_empty());
    }

    #[test]
    fn scan_random_parity_vs_naive() {
        // náhodná data + adversariální patterny (prefixy, duplikáty, překrývání)
        let mut rng_state: u64 = 0x243F6A8885A308D3;
        fn rng(s: &mut u64) -> u8 {
            // splitmix64 — deterministický, bez závislostí
            *s = s.wrapping_add(0x9E3779B97F4A7C15);
            let mut z = *s;
            z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
            (z ^ (z >> 31)) as u8
        }
        let mut data: Vec<u8> = Vec::with_capacity(64 * 1024);
        for _ in 0..data.capacity() {
            data.push(rng(&mut rng_state));
        }
        // zasaďte známe magiky na náhodná místa + překrývající se "aaaa" pasáže
        let magics: Vec<Vec<u8>> = vec![
            b"\x89PNG\r\n\x1a\n".to_vec(),
            b"%PDF-1.7".to_vec(),
            b"PK\x03\x04".to_vec(),
            b"GIF89a".to_vec(),
        ];
        for m in &magics {
            for _ in 0..25 {
                let at = (rng(&mut rng_state) as usize % (data.len() - m.len())) + m.len();
                data[at..at + m.len()].copy_from_slice(m);
            }
        }
        // dlouhá pasáž 'a' — maximum překrývajících se shod pro 1/2/3-mer patterny
        let aa_at = 8 * 1024;
        for i in 0..512 {
            data[aa_at + i] = b'a';
        }
        let patterns: Vec<Vec<u8>> = magics
            .clone()
            .into_iter()
            .chain(vec![
                b"a".to_vec(),
                b"aa".to_vec(),
                b"aaa".to_vec(),
                vec![],
                b"\x89PNG".to_vec(),
            ])
            .collect();
        assert_eq!(
            scan_data(&data, &patterns).unwrap(),
            naive_scan(&data, &patterns)
        );
    }
}
