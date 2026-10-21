# Umi-OCR 3.0.3 Corresponding Source and Delivery Contract

## Product and source scope

Product 3.0.3 combines the 3.0.2 batch-queue, ordering/removal, document re-OCR,
ignore-region and hot-settings fixes with retirement of the unsafe in-place
source-refresh tool and isolation of CUDA plugin source in combined candidates.
See [the application draft](docs/RELEASE_3.0.3_DRAFT.md),
[the CUDA draft](docs/RELEASE_CUDA_3.0.3_DRAFT.md),
[acceptance boundaries](docs/RELEASE_3.0.3_ACCEPTANCE.md) and
[the review contract](docs/RELEASE_3.0.3_REVIEW.md).

Corresponding source is maintained in these repositories:

- Application and base distribution: https://github.com/Dominic485649/UMI-OCR
- CUDA plugin: https://github.com/Dominic485649/UMI-OCR_plugins
- Original project and attribution: https://github.com/hiroi-sora/Umi-OCR

The public product scope is the base application and CUDA plugin only. CPU and
PaddleOCR-VL plugins are not public assets. This exclusion does not waive source
obligations for separately distributed covered binaries, including paid delivery.
Assistant configuration, instructions, sessions, user settings, caches and
historical runtime binaries are not release-source inputs.

## Frozen source and artifact evidence

Each formal product must retain its own corresponding source, build scripts,
dependency locks, patches, notices and applicable locked third-party source
materials. Its `source/` mirror and `source-snapshot.zip` must agree;
`source-snapshot.json` records member hashes and `source-provenance.json` records
the parent revision, local-change inclusion, version and source archive hash.
A parent revision is provenance, not a claim that uncommitted inputs were already
in that commit. The public source export must match the actual frozen source and
its matching public commit/tag, not merely share a version string.

A CUDA overlay generated from a combined tree must use the plugin's explicitly
identified corresponding source, version, snapshot and provenance. It must not
fall back to the host root. An older combined tree without an explicit plugin
source must be rejected and reassembled, not assigned a guessed source.

Once the actual base and CUDA overlay source and payload have been frozen for
review, do not refresh or replace their contents. Final artifact-derived reports
belong in the product's `LICENSES/` metadata, with CUDA overlay metadata under
`LICENSES/plugins/win32_PaddleOCRv6_CUDA/`. These include `source-delivery.json`,
`current-source-e2e.json` and `RELEASE_EVIDENCE.json` / `RELEASE_EVIDENCE.md`.
Do not copy a later PASS back into canonical `source/`, change the frozen source
or regenerate its snapshot to make a result appear to belong to that source.
A verification output is not a replacement for explicit, current gate inputs.

## Delivery sequence and review gate

1. Prepare the base and CUDA products in new directories and run real local
   acceptance. The 2026-10-22 rebuild plan uses non-`LocalCandidate` preparation
   with `-SkipArchive`; this step is not a formal archive or publication PASS.
2. Freeze the actual base and CUDA overlay source and payload, their identities
   and bindings. Review and later gates must refer to these same files.
3. Give the user the actual prepared program, both Release texts, evidence,
   unverified limitations and a project-scoped cleanup preview. Obtain explicit
   approval of this round's program and texts before updating public main/tags.
   Permission to replace an existing tag is not approval of an unreviewed program.
4. Only after that review approval, update the matching public source and tags.
   A formal fresh source-delivery gate must wait until the public tags match.
5. Run fresh gates against those frozen products and matching public source, with
   explicit inputs bound separately to the base and GPU artifact kinds. Historical
   reports, a version match or user approval alone cannot supply a missing PASS.
6. Only after the applicable gates succeed, use restricted finalization to derive
   artifact metadata, create formal archives, reinstall them into a new directory
   and verify the installed products before publication. Finalization must not
   rebuild or refresh the reviewed source/payload. A failed or incomplete required
   gate remains blocking.

The final local delivery consists of an application directory reinstalled from
the final archives with the matching CUDA plugin, a base-only archive without an
OCR inference plugin, and the CUDA plugin archive. External audit/work files stay
under `build/audit`, not at the release root. Product and Host API versions are
different fields: product 3.0.3 retains CUDA Host API compatibility `>=2.7,<3.0`.

## Dated state: 2026-10-22, before this round's fresh rebuild

This is a source-document freeze point, not a live assertion about every later
artifact. Subsequent review, gate and publication results must be recorded in
newly identified review/audit records and the actual artifact metadata, not
backfilled as PASS into this canonical source document.

- Internal starting HEAD: `b0518fff09d0c0dc730c2bd629a1e1415b354094`.
- The maintainer's public host `main` and `v3.0.3` point to
  `fa5613d4d184c46a4e212ce589f19caa96a3f7d6`.
- The public CUDA `v3.0.3` points to
  `f9235da667bf87dbc070029169aa0c228701b9a0`.
- Both `v3.0.3` source tags already exist publicly. Neither 3.0.3 binary Release
  has been created, uploaded or published. The retained formal binary download
  links at this cutoff are for `v3.0.1`; a source tag is not a binary release.
- This round is to repair the formal gate wiring and perform a fresh
  non-`LocalCandidate`, `-SkipArchive` rebuild. That new build has not yet run at
  this freeze point; no new hashes, PASS or user acceptance are asserted.
- The user has permitted replacement of the two public `v3.0.3` tags, subject to
  renewed review of this round's actual program and texts before main/tag updates.
  The 3.0.2 tags and drafts remain historical and unchanged.

## Historical evidence, not this round's acceptance

The 2026-10-21 R2 products built from internal `b0518fff` did complete base and
combined regressions, real hot GUI/plugin switching, Windows tray and HTTP
readiness/normal exit, GPU workflows, archive reinstallation, corresponding-source
checks and model-byte checks. The original records are under
`build/audit/3.0.3/review-20261021-r2/`, including `REVIEW_REQUEST.md`,
`automated-local-candidates.json`, the install-integrity reports and
`local-source-products-verified.json`. R2 must not be described as never built or
never tested. The R2 program and texts were subsequently delivered for review,
and the user authorized the main/tag push that followed; a review JSON's earlier
creation-time status does not negate that later authorization. That approval does
not carry forward to this round's new program. Historical R2 results are not PASS
for the 2026-10-22 rebuild.

R2 did not complete the full manual/HDR checklist, native Explorer/mouse input,
the entire GUI single-document re-OCR/old-output protection sequence, or mixed
HDR/SDR and multi-display coverage. Old HDR feedback is not a new capture receipt
or acceptance of this round. R1 (`2394ea5d`) remains an earlier automated-test
record which did not cover the later combined-CUDA source-isolation fix.

The 3.0.2 local archives were frozen from internal revision
`2a038a48a443140ee3b7f90757e29d72830c094b`. They retain their original source,
hashes, provenance, notices and historical publication status; see
[the local delivery notes](docs/RELEASE_3.0.2_LOCAL.md). Do not rename them as
3.0.3, refresh their source or reuse their hashes/results for new files. The
retired refresh entry point only reports that it is disabled; it must not patch
frozen products or access sibling plugin projects.

## Licenses and unchanged inputs

The original Umi-OCR MIT `LICENSE`, hiroi-sora copyright notices and attribution
remain in place. Fork-added or modified code and the combined PyMuPDF host retain
AGPL-3.0-or-later terms. NVIDIA runtime and model terms are identified separately;
preserve all applicable third-party notices and source/license materials.
This update changes neither the recognition engine, dependency locks nor model
URLs, bytes or precision, and makes no new model or trademark authorization claim.
