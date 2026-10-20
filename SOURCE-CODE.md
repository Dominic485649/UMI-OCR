# Umi-OCR 3.0.2 Candidate Source Code Notice

The main branch contains the current and previous application updates, including
3.0.2 candidate code and draft release notes. A source update does not create a
3.0.2 tag or GitHub Release and does not authorize binary publication while the
artifact gates remain blocked. See [the application draft](docs/RELEASE_3.0.2_DRAFT.md)
and [the CUDA draft](docs/RELEASE_CUDA_3.0.2_DRAFT.md).

The existing local candidate archives were frozen from internal revision
`2a038a48a443140ee3b7f90757e29d72830c094b`. They retain their original corresponding-source
snapshot, member hashes, provenance and third-party materials. New documentation
or public source commits do not retroactively change those archives, their source
identity, or their blocked publication status. The earlier
[local delivery notes](docs/RELEASE_3.0.2_LOCAL.md) describe that local-only phase.

The existing published formal release tag remains `v3.0.1`. Its public source belongs to these repositories:

- Application and base distribution: https://github.com/Dominic485649/UMI-OCR
- CUDA plugin: https://github.com/Dominic485649/UMI-OCR_plugins
- Original project and attribution: https://github.com/hiroi-sora/Umi-OCR

Release archives contain a `source/` mirror and `source-snapshot.zip` with the
source, build scripts, dependency locks, patches, notices, and applicable locked
third-party corresponding-source materials used for that product.
`source-snapshot.json` records the member hashes. `source-provenance.json` records
the parent revision, inclusion of local changes, version, and source archive hash.
The public Git export is a clean snapshot; a parent revision is provenance, not a
claim that uncommitted inputs were already in that commit.

CPU and PaddleOCR-VL plugins are not part of this public release. This exclusion
does not waive source obligations for separately distributed covered binaries,
including paid delivery. Assistant configuration, instructions, sessions, user
settings, caches, and historical runtime binaries are not release-source inputs.

The original Umi-OCR MIT `LICENSE`, hiroi-sora copyright notices, and attribution
remain in place. Fork-added or modified code and the combined PyMuPDF host
retain AGPL-3.0-or-later terms. NVIDIA runtime and model terms are identified
separately. Preserve all applicable third-party notices and license materials.
