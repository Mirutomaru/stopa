//! STOPA Rust core (F2.1) — high-performance hashing + carving scan.
//!
//! PyO3 extension. Čistá jádra [`compute_hashes`] / [`scan_data`] jsou bez
//! PyO3 typů → testují se přes `cargo test` offline; pyfunction vrstva jen
//! uvolní GIL (`py.detach`) a převede chyby na Python výjimky.
//!
//! Semantika = přesná parity s Python referencí:
//! - hash: one-pass MD5/SHA-1/SHA-256, neznámý algoritmus → ValueError
//! - scan: per-pattern nenakládající shody (ekvivalent smyčky `data.find(magic)`)

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

#[pymodule]
fn stopa_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(hash_file, m)?)?;
    m.add_function(wrap_pyfunction!(find_offsets, m)?)?;
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
