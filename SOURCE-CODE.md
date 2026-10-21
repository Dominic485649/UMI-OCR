# Umi-OCR 3.0.3 Candidate Source Code Notice (R2 Pending Validation and Review)

The main branch prepares a 3.0.3 local candidate R2 combining the 3.0.2 core fixes
with retirement of the unsafe in-place candidate-source refresh tool and a fix for
host/plugin source mixing when generating CUDA overlays from combined candidates.
See [the application draft](docs/RELEASE_3.0.3_DRAFT.md) and
[the CUDA draft](docs/RELEASE_CUDA_3.0.3_DRAFT.md). Updated source and draft notes
do not mean a binary release is complete. No public `v3.0.3` tag or GitHub Release
has been created. The user must review the actual R2 application and release
text and explicitly approve before any push; public binary distribution also
requires its release gates. A general request to release or confirmation of HDR
behavior is not that review approval.

The existing 3.0.2 local candidate archives were frozen from internal revision
`2a038a48a443140ee3b7f90757e29d72830c094b`. They retain their original corresponding-source
snapshot, member hashes, provenance and third-party materials. New documentation
or public source commits do not retroactively change those archives, their source
identity, or their blocked publication status. Historical tags and release notes
remain unchanged. The earlier
[local delivery notes](docs/RELEASE_3.0.2_LOCAL.md) describe that local-only phase.
Do not rename those archives as 3.0.3 or reuse their verification results or hashes
for a new candidate.

New 3.0.3 candidates must be rebuilt in a fresh directory so runtime payload,
corresponding source and provenance agree. The retired refresh entry point only
reports that it is disabled; it must not patch frozen candidates or access sibling
plugin projects.

Generating a CUDA overlay from a combined candidate must use the plugin's own
explicitly identified corresponding source, version, source snapshot and
provenance. It must not fall back to the host root and accidentally package host
source as plugin source. An older combined candidate without an explicit plugin
source must be rejected and reassembled; the tool must not guess a source from
the host or elsewhere. This packaging fix upgrades neither the recognition
engine nor the models or dependencies.

The first-round R1 candidate built from `2394ea5d` completed its automated
regressions. Those results do not cover the subsequently added source-mixing fix.
R2 containing the fix must be rebuilt and undergo current-round automated and
final-package verification, followed by user review. R2 validation is pending;
R1 results and hashes must not be reused as R2 evidence. Record results and hashes
only for the actual frozen R2 files.

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

The public scope remains the base application and CUDA plugin only. CPU and
PaddleOCR-VL plugins are not public assets. This exclusion does not waive source
obligations for separately distributed covered binaries, including paid delivery.
Assistant configuration, instructions, sessions, user settings, caches, and
historical runtime binaries are not release-source inputs.

The original Umi-OCR MIT `LICENSE`, hiroi-sora copyright notices, and attribution
remain in place. Fork-added or modified code and the combined PyMuPDF host
retain AGPL-3.0-or-later terms. NVIDIA runtime and model terms are identified
separately. Preserve all applicable third-party notices and license materials.
This version update changes neither dependency locks nor model URLs, bytes or
precision, and makes no new model or trademark authorization claim.
