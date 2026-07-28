# pgvector covers our scale; a dedicated vector DB does not pay for itself yet

**Question:** Should we move our embedding search off Postgres to a dedicated vector database?
**Scope:** Read-heavy workload, ~2M embeddings today, 768 dimensions. Excludes multi-tenant isolation.
**Mode:** standard · **Sources:** 10 · **Date:** 2026-07-14

---

## Answer

At our current corpus size, Postgres with pgvector serves p95 queries in under 40ms [1], which is within our 100ms budget. Dedicated vector databases show a decisive advantage only above roughly 10 million vectors [2][3]. Migrating now would add an operational dependency without buying measurable latency.

---

## Findings

### 1. pgvector's HNSW index closed most of the historical latency gap

The HNSW index shipped in pgvector 0.5.0 reduced p95 latency by 34% relative to the earlier IVFFlat approach on a 2M-vector corpus [1]. Independent benchmarking on comparable hardware places pgvector within 1.4x of a dedicated engine at this scale [4], a margin that sits well inside our latency budget. The gap widens materially only as the corpus grows [2].

### 2. The crossover point is corpus size, not query volume

Benchmarks that vary corpus size while holding queries per second constant find the decisive break at approximately 10 million vectors [2][3]. Below that, the dedicated engines' advantage is real but small in absolute terms; above it, recall at fixed latency degrades sharply for pgvector [5]. Our 2M corpus is growing at roughly 15% per quarter [6], which puts the crossover several years out.

### 3. Operational cost of a second datastore is routinely underestimated

Teams reporting migrations describe the ongoing burden as the dominant cost: a second consistency model, a second backup path, and dual-write complexity during reindexing [7][8]. One engineering write-up attributes 60% of its post-migration incidents to synchronisation drift between the primary database and the vector store [7]. Staying on Postgres also keeps index maintenance inside a single, well-understood VACUUM path [9], and avoids the general overhead that polyglot persistence imposes on on-call rotations [10].

---

## So What

On this evidence, the reasonable move is to stay on pgvector and revisit when the corpus approaches 8 million vectors, which our current growth rate puts roughly three years out [6]. The decision would change if query patterns shifted toward high-QPS filtered search, where dedicated engines' metadata filtering is genuinely stronger [5].

The second-order point that the sources do not state outright: the migration cost is not symmetric. Moving to a dedicated store later is a well-trodden path; moving back after discovering the operational burden is not.

---

## Limitations

The benchmarks cited [2][3][4] all run on synthetic corpora, and none tests our specific filtered-search pattern. No source was found that benchmarks pgvector against dedicated engines under sustained concurrent write load, which is a genuine gap given our ingestion pattern. Two of the migration write-ups [7][8] are vendor-adjacent and may understate dedicated-engine friction.

---

## Bibliography

[1] pgvector maintainers (2025). "pgvector 0.5.0 release notes: HNSW indexing". GitHub. https://github.com/pgvector/pgvector/releases (Retrieved: 2026-07-14)
[2] Chen, L. et al. (2025). "Scaling behaviour of vector indexes". arXiv. https://arxiv.org/abs/2501.00001 (Retrieved: 2026-07-14)
[3] ANN-Benchmarks Project (2026). "Recall-latency curves across engines". https://ann-benchmarks.com (Retrieved: 2026-07-14)
[4] Okafor, N. (2026). "Benchmarking pgvector against dedicated engines". Example Engineering Blog. https://example.com/pgvector-bench (Retrieved: 2026-07-14)
[5] Duarte, M. & Silva, R. (2025). "Filtered search in approximate nearest neighbour indexes". IEEE. https://ieee.org/document/123456 (Retrieved: 2026-07-14)
[6] Internal Platform Team (2026). "Embedding corpus growth, Q1-Q2 2026". Internal memo. https://example.com/internal-growth (Retrieved: 2026-07-14)
[7] Whitfield, J. (2026). "What our vector database migration actually cost". Example Corp Engineering. https://example.com/migration-postmortem (Retrieved: 2026-07-14)
[8] Alvarez, P. (2025). "Dual-write patterns and their failure modes". Example Journal. https://example.com/dual-write (Retrieved: 2026-07-14)
[9] Postgres Documentation (2026). "Index maintenance and VACUUM". https://www.postgresql.org/docs/current/routine-vacuuming.html (Retrieved: 2026-07-14)
[10] Nakamura, S. (2026). "Operational overhead of polyglot persistence". Example Review. https://example.com/polyglot (Retrieved: 2026-07-14)
