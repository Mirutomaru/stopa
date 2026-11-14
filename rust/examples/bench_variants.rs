//! F2.3 mikrobenchmark — varianty hot loopu, měříme co skutečně stojí.
//! Spustit: cargo run --release --example bench_variants
use std::fs::File;
use std::io::Read;
use sha2::{Digest, Sha256};

const CHUNK_SIZE: usize = 4 * 1024 * 1024;

// z lib.rs (stejné hodnoty) + truncované váhy pro u16 variantu
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
const W16: [u16; 32] = [
    0x861e, 0x704e, 0xc204, 0xcf9a, 0x3bf4, 0x43c1, 0xd757, 0xdc45,
    0x83f2, 0x0725, 0xc7bd, 0xe29a, 0x9792, 0x4e4d, 0x50c5, 0x22a6,
    0xc890, 0x0786, 0x6181, 0x10da, 0xaf12, 0xafd3, 0x789a, 0xe4dc,
    0x4d7d, 0x7cbb, 0x8424, 0x82f3, 0x2054, 0xf448, 0xe1e3, 0xe4ad,
];

fn bench(name: &str, path: &str, variant: u8) {
    let mut file = File::open(path).expect("open");
    let n_file = file.metadata().unwrap().len() as usize;
    let avg_size = 8192usize;
    let min_size = 4096usize;
    let max_size = 16384usize;
    let mask = (avg_size - 1) as u64;
    let mut ring = vec![0u8; avg_size];
    let mut hash: u64 = 0;
    let mut h16: u16 = 0;
    let mut block_start = 0usize;
    let mut blocks = 0usize;
    let mut buf = vec![0u8; CHUNK_SIZE];
    let mut sha_state = Sha256::new();
    let mut sha_up_to_bench = 0usize;
    let mut off = 0usize; // absolutní offset buf[0] v aktuální iteraci (varianta 4)
    let t0 = std::time::Instant::now();

    loop {
        let chunk_start = off;
        let n = file.read(&mut buf).unwrap();
        if n == 0 { break; }
        if variant == 4 { sha_up_to_bench = 0; } // bench klona: chunk-relativní SHA offset
        for i in 0..n {
            let b = buf[i];
            let pos = i; // relativní stačí pro bench (sloty cyklické)
            let pos_abs = chunk_start + i; // varianta 4: ABSOLUTNÍ pos jako v produkci
            let slot = pos & (avg_size - 1);
            match variant {
                // 0: aktuální fast path (u64 + W*byte, plný hash)
                0 => {
                    let w = BUZ_TABLE[pos & 31];
                    if pos >= avg_size { hash = hash.wrapping_sub(w * u64::from(ring[slot])); }
                    ring[slot] = b;
                    hash = hash.wrapping_add(w * u64::from(b));
                    let len = pos + 1 - block_start;
                    if (pos + 1 >= avg_size && len >= min_size && hash & mask == 0) || len >= max_size { blocks += 1; block_start = pos + 1; }
                }
                // 1: truncovaný u16 hash + delta násobení (w*(b-old), bez plného u64)
                1 => {
                    let w16 = W16[pos & 31];
                    let old = ring[slot];
                    if pos >= avg_size {
                        h16 = h16.wrapping_add(w16 * (b as u16).wrapping_sub(old as u16));
                    }
                    ring[slot] = b;
                    // pozor: pro bench jen add část plně — viz poznámka níže
                    let len = pos + 1 - block_start;
                    if (pos + 1 >= avg_size && len >= min_size && ((h16 as u64) & mask) == 0) || len >= max_size { blocks += 1; block_start = pos + 1; }
                }
                // 2: jen ring evict+store, žádný hash (dno: kolik stojí paměťová část)
                2 => {
                    let old = ring[slot];
                    let _ = old.wrapping_add(b);
                    ring[slot] = b;
                    let len = pos + 1 - block_start;
                    if len >= max_size { blocks += 1; block_start = pos + 1; }
                }
                // 3: jen hranicová podmínka nad statickým hashem (dno: porovnání)
                3 => {
                    let len = pos + 1 - block_start;
                    if (pos + 1 >= avg_size && len >= min_size && hash & mask == 0) || len >= max_size { blocks += 1; block_start = pos + 1; }
                }
                // 4: KLONA produkčního fast16 loopu — ABSOLUTNÍ pos, warmup jen na startu souboru
                4 => {
                    let w16 = W16[pos_abs & 31];
                    if pos_abs >= avg_size {
                        h16 = h16.wrapping_add(w16 * (b as u16).wrapping_sub(ring[slot] as u16));
                    } else {
                        h16 = h16.wrapping_add(w16 * (b as u16));
                    }
                    ring[slot] = b;
                    let hb: u64 = h16 as u64;
                    let len = pos_abs + 1 - block_start; // absolutní délka bloku
                    if (pos_abs + 1 >= avg_size && len >= min_size && hb & mask == 0) || len >= max_size {
                        blocks += 1;
                        // SHA bulk flush jako v produkci: update slice buf[sha_up_to..=i]
                        sha_state.update(&buf[sha_up_to_bench..(i + 1)]);
                        let _ = sha_state.finalize_reset();
                        sha_up_to_bench = i + 1;
                        block_start = pos_abs + 1; // absolutní offset za hranicí
                    }
                }
                _ => unreachable!(),
            }
        }
        // chunk-end zbytek (var 4, produkční semantika — blok může přesahovat chunk)
        if variant == 4 && n > sha_up_to_bench {
            sha_state.update(&buf[sha_up_to_bench..n]);
        }
        off += n;
    }
    // produkční final flush (lib.rs): závěrečný částečný blok za poslední hranicí
    if variant == 4 && block_start < n_file {
        blocks += 1;
        let _ = sha_state.finalize_reset();
    }
    let dt = t0.elapsed();
    println!(
        "{}: {:6.2} ms  ({:5.0} MB/s)  blocks={} ({} B soubor)",
        name,
        dt.as_secs_f64() * 1000.0,
        n_file as f64 / 1e6 / dt.as_secs_f64(),
        blocks,
        n_file
    );
}

fn main() {
    let path = std::env::args().nth(1).unwrap_or_else(|| "/tmp/f23_bench/disk_e2e.img".to_string());
    bench("0 fast-path u64   ", &path, 0);
    bench("1 trunc-u16 delta ", &path, 1);
    bench("2 ring-only       ", &path, 2);
    bench("3 cond-only       ", &path, 3);
    bench("4 prod-clone fast16", &path, 4);
}
