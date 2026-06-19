# Path-Preserving Upload Flow Change Specification

## 1. Purpose

This document defines the required changes to support recursive scanning under `image_root` and to preserve the source folder structure through upload, queueing, processing, and final storage.

This change should be implemented with performance and stability as the primary priorities.
The deployment context is an internal company network without public internet exposure, so external-facing security hardening is not the main driver for this change.
Basic path-safety validation is still required to prevent malformed internal data from breaking worker behavior.

The target use case is a machine-side directory structure such as:

```text
D:/B07-01/
  [batch-no]/
    [NG-or-OK]/
      [original-images-and-info-images]
```

The system should be able to:

- Scan image files inside nested subdirectories under `image_root`
- Upload files without losing their relative path
- Store processed files on the server using that relative path

---

## 2. Current Limitation

The current implementation does not support this requirement.

### 2.1 Machine Client Scan Scope

Current behavior in `machine_client/disk_queue.py` only scans the first level under `image_root`.

Current limitation:

- Uses `image_root.iterdir()`
- Does not recurse into child folders
- Nested paths such as `D:/B07-01/LOT001/NG/*.jpg` are ignored

### 2.2 Batch Packaging Behavior

Current zip packaging stores only the filename.

Current limitation:

- Uses `archive.write(file_path, arcname=file_path.name)`
- Loses the relative path under `image_root`
- Two files with the same name from different folders can collide logically

### 2.3 Worker Output Layout

Current worker output is organized only by machine and date.

Current limitation:

```text
processed/<machine>/<YYYY>/<MM>/<DD>/
```

The original path such as `B07-01/LOT001/NG/` is not preserved.

---

## 3. Target Behavior

### 3.1 Recursive Machine-Side Discovery

The machine client must recursively scan all supported image files under `image_root`.

Example:

```text
image_root = D:/
```

Valid source file examples:

```text
D:/B07-01/LOT001/NG/img001.jpg
D:/B07-01/LOT001/OK/img002.jpg
D:/B07-01/LOT002/NG/info_01.png
```

### 3.2 Preserve Relative Path in Batch

Each file must retain its relative path from `image_root`.

Example relative paths:

```text
B07-01/LOT001/NG/img001.jpg
B07-01/LOT001/OK/img002.jpg
B07-01/LOT002/NG/info_01.png
```

### 3.3 Preserve Relative Path in Server Output

The worker must store processed output using the machine root and the preserved relative path.

Recommended target layout:

```text
processed/<machine>/B07-01/LOT001/NG/img001.webp
processed/<machine>/B07-01/LOT001/OK/img002.webp
processed/<machine>/B07-01/LOT002/NG/info_01.webp
```

If Pillow is unavailable and fallback copy mode is used, the same relative path should still be preserved.

---

## 4. Scope of Change

The change affects the following areas:

- Machine-side file discovery
- Machine-side source indexing
- Zip packaging and manifest format
- Upload metadata schema
- Worker extraction and output mapping
- Validation and collision handling
- Documentation and verification

The upload API route itself does not need a breaking contract change if the relative path is carried inside the zip and manifest.

### 4.1 Priority Order for This Change

The implementation priority should be:

1. Stability and recovery correctness
2. Machine-side and worker-side performance
3. Functional path preservation
4. Basic internal safety checks

This means the design should prefer simpler, predictable behavior over extra abstraction or over-engineered security controls.

---

## 5. Detailed Design Changes

## 5.1 Machine Client Discovery Logic

### Current

- Iterate only over direct children of `image_root`

### Required

- Recursively walk all files under `image_root`
- Keep filtering by supported image extensions
- Continue respecting minimum file age before staging

### Recommended implementation

- Replace first-level iteration with recursive traversal such as `rglob("*")`
- Process only files, not directories
- Calculate a stable relative path using:
  - `relative_path = source_path.relative_to(image_root)`
- Keep the implementation simple enough that scan behavior is easy to reason about during recovery and troubleshooting
- Use segmented scan units so one cycle does not walk the full tree
- Prefer scan units aligned to production structure such as `[product]/[batch-no]`

### Performance note

- Recursive scanning will increase filesystem work
- The implementation should minimize repeated work and preserve the current dedup behavior
- If scan cost becomes too high on real machines, scan throttling or segmented traversal may be required

### Implemented strategy

The implemented strategy should be:

- Discover scan units from the top two levels where possible
- Scan only a limited number of units per cycle
- Prioritize units that appear changed according to the directory index
- Use round-robin traversal for unchanged units so old branches are still revisited eventually

### Acceptance criteria

- Files nested at any depth under `image_root` are discovered
- Non-image files are still ignored
- The same minimum age behavior is preserved

---

## 5.2 Machine Client Source Index Structure

### Current

The source index uses absolute path as the key.

### Required

The system may continue using absolute path as the dedup key, but the staged metadata must also include the relative path.

Recommended source index behavior:

- Dedup key: absolute source path
- Signature: `mtime_ns:size`
- Additional staged metadata: relative path under `image_root`

### Implemented source index expectation

The source index should persist at least:

- `last_signature`
- `relative_path`
- `last_staged_relpath`
- `last_seen_at`

This allows the client to:

- Avoid re-uploading the same unchanged file
- Reconstruct the original tree during packaging

---

## 5.3 Staging Layout

### Problem

The current staged directory stores copied files only by final filename.

This creates ambiguity when two nested folders contain the same filename.

Example conflict:

```text
D:/B07-01/LOT001/NG/result.jpg
D:/B07-01/LOT002/NG/result.jpg
```

### Required

The staged area must preserve enough path information to avoid collisions.

### Recommended options

Option A: Preserve full relative directory in `staged/`

```text
staged/B07-01/LOT001/NG/result.jpg
staged/B07-01/LOT002/NG/result.jpg
```

Option B: Store files in a flat staging area but keep a manifest mapping

Option A is recommended because it is simpler to inspect and debug.
It also reduces ambiguity during retry, cleanup, and restart recovery.

### Implemented staged-file expectation

To avoid same-name collisions and preserve retry correctness, the staged copy should:

- keep the original relative parent path
- use an internal unique suffix derived from file path and signature
- preserve the original relative path only in manifest and zip archive member name

This allows two versions of the same source file to exist temporarily without overwriting each other while still restoring the original server-side path.

### Acceptance criteria

- Duplicate filenames in different source folders do not overwrite each other
- Batch creation can reconstruct the original relative path cleanly

---

## 5.4 Batch Manifest Format

### Current

Manifest image entries are only filenames.

### Required

Each manifest image record must include at least:

- source filename
- relative path
- optional staged path

### Recommended manifest shape

```json
{
  "batch_id": "20260619T101500000000",
  "machine_id": "MC01",
  "created_at": "2026-06-19T10:15:00Z",
  "attempts": 0,
  "checksum_sha256": "...",
  "idempotency_key": "MC01:20260619T101500000000:abcd1234",
  "images": [
    {
      "name": "img001.jpg",
      "relative_path": "B07-01/LOT001/NG/img001.jpg"
    },
    {
      "name": "info_01.png",
      "relative_path": "B07-01/LOT002/NG/info_01.png"
    }
  ]
}
```

### Acceptance criteria

- Worker can determine intended output subdirectory without guessing
- Manifest remains deterministic and retry-safe

---

## 5.5 Zip Archive Format

### Current

- `arcname=file_path.name`

### Required

- `arcname` must use the relative path under `image_root`

### Example

Instead of:

```text
img001.jpg
```

The zip entry should be:

```text
B07-01/LOT001/NG/img001.jpg
```

### Acceptance criteria

- Extracted temp workspace contains the same tree shape as under `image_root`
- Two files with the same filename but different folders remain distinct

---

## 5.6 Upload Metadata Schema

### Current

Server upload metadata records:

- batch filename
- stored path
- image count
- checksum
- idempotency key

### Required

The upload metadata should include path-preservation compatibility markers.

Recommended additions:

- `path_mode`: `flat` or `relative_tree`
- `root_hint`: optional source root label if needed for debugging

Example:

```json
{
  "job_id": "MC01-20260619T101500000000",
  "machine_id": "MC01",
  "path_mode": "relative_tree",
  "stored_path": "runtime/server-storage/raw/MC01/2026/06/19/batch.zip"
}
```

This is not mandatory for first implementation, but recommended for observability.

---

## 5.7 Worker Extraction and Output Mapping

### Current

Worker writes outputs only to:

```text
processed/<machine>/<YYYY>/<MM>/<DD>/
```

### Required

Worker must preserve the extracted relative path below the machine root.

### Recommended output mapping rule

For each extracted file:

```text
output_root = processed/<machine>/
output_path = output_root / relative_parent / converted_filename
```

Where:

- `relative_parent` is `B07-01/LOT001/NG/`
- `converted_filename` is either `img001.webp` or fallback original name

### Acceptance criteria

- Output tree reflects source tree
- Parent directories are created automatically
- Existing collision handling still works when the same relative path already exists

---

## 5.8 Worker Validation

### Required validation rules

- No path traversal entries such as `../`
- No absolute paths in archive members
- Only files under the extracted batch root are accepted
- Unsupported file extensions are ignored or rejected according to current validation policy

### Internal safety rule

The worker must normalize zip member paths and reject any entry that escapes the extraction workspace.

This rule exists mainly for stability and data-integrity reasons in an internal environment, not as a primary internet-facing security control.

---

## 5.9 Failure and Retry Behavior

The following behavior must remain unchanged:

- Client deletes local batch only after ACK
- Inflight recovery on restart still works
- Retry count behavior remains deterministic
- Failed batches can still be copied into investigation storage

Path preservation must not weaken existing recovery guarantees.

---

## 6. Output Layout Recommendation

### Recommended final processed layout

```text
/processed/
  <machine>/
    B07-01/
      LOT001/
        NG/
          img001.webp
        OK/
          img002.webp
      LOT002/
        NG/
          info_01.webp
```

### Optional variant

If the top-level product folder such as `B07-01` is not needed, the system could store only the subtree below it.

This should be configurable only if there is a real business need.

Default recommendation:

- Preserve the full relative path from `image_root`

---

## 7. Files That Need Modification

### 7.1 Machine Client

- `machine_client/disk_queue.py`
  - recursive scan
  - staged path preservation
  - manifest structure update
  - zip `arcname` update
  - cleanup logic update for nested paths

### 7.2 Server

- `server/storage.py`
  - optional metadata additions for path mode

### 7.3 Worker

- `worker/processor.py`
  - preserve extracted relative path in final output
  - secure path normalization
  - parent directory creation for nested output

### 7.4 Documentation

- `README.md`
- `docs/system-design-spec.md`
- `docs/operations-runbook.md`

---

## 8. Backward Compatibility Strategy

### Recommended approach

Support both modes during rollout:

- `flat` legacy batch mode
- `relative_tree` new batch mode

### Reason

This avoids breaking older clients immediately if multiple machines are updated in stages.

### Worker compatibility behavior

- If zip entries are flat and manifest has no relative path, use legacy flat output logic
- If manifest and zip contain relative paths, use path-preserving logic

This compatibility layer is recommended if mixed-version deployment is expected.

If all machines can be upgraded together, the implementation may choose a direct cutover instead.

### Stability preference

If mixed-version deployment is likely, compatibility support is preferred over a cleaner one-shot rewrite.
This reduces rollout risk and lowers the chance of worker-side regressions during staged machine upgrades.

---

## 9. Risks

For this project, the most important risks are performance and stability risks.
Safety checks remain necessary, but they should stay lightweight and should not dominate the implementation complexity.

### 9.1 Duplicate File Names

Risk:

- Two files with the same filename from different subfolders collide in current staging

Mitigation:

- Preserve subtree in staged area

### 9.1.1 End-to-End Collision Risk

Risk:

- If any one stage uses only filename instead of relative path, files from different source folders may overwrite each other
- This can happen in staging, manifest generation, zip creation, extraction mapping, or final output writing

Mitigation:

- Use relative path as the canonical identity through the full pipeline
- Verify that staged layout, manifest entries, zip members, worker extraction, and final output all agree on the same relative path

### 9.2 Path Traversal in Zip

Risk:

- Malicious or malformed zip path escapes worker temp root

Mitigation:

- Normalize and validate all member paths

### 9.2.1 Unsafe Absolute or Escaping Paths

Risk:

- Archive members using absolute paths or `..` can escape the intended worker extraction directory
- A malformed batch could write files outside temp or processed roots

Mitigation:

- Reject absolute paths
- Reject normalized paths containing parent traversal
- Ensure final resolved output path remains under the intended output root

### 9.3 Deep Directory Trees

Risk:

- Long path depth increases temp and output path complexity

Mitigation:

- Add path length checks where required by platform constraints

### 9.3.1 Recursive Scan Cost

Risk:

- Changing from first-level scan to recursive scan increases filesystem IO and CPU usage
- Large historical directory trees may slow each scan cycle and increase machine-side load

Mitigation:

- Benchmark against real factory directory size
- Consider excluding known non-image branches if needed
- Keep minimum age filtering and dedup index efficient

### 9.4 Cleanup Logic

Risk:

- Existing cleanup logic assumes flat staged entries

Mitigation:

- Update cleanup routines to remove nested staged files safely

### 9.4.1 Retry and Recovery Regression

Risk:

- Existing retry, inflight recovery, and sent-batch cleanup paths were designed around flat files
- Nested layout may leave orphan directories, stale manifests, or uncleaned files after restart or upload success

Mitigation:

- Re-test recovery with nested staged files
- Ensure cleanup removes empty directories safely after file deletion
- Verify restart recovery still returns inflight batches to ready state without path loss

### 9.5 Backward Compatibility Risk

Risk:

- Older machine clients may continue producing flat batches while newer clients produce path-preserving batches
- A worker that assumes only one format may fail or mis-store files

Mitigation:

- Support both `flat` and `relative_tree` modes during rollout
- Detect mode from manifest and archive member paths

### 9.6 Relative Path Calculation Risk

Risk:

- If relative path calculation is inconsistent, files may be stored in the wrong location
- Path separator differences between Windows and Linux may also cause subtle bugs

Mitigation:

- Always compute relative paths from `image_root`
- Normalize path separators before writing manifest and archive entries
- Use one canonical path format in transport and worker logic

### 9.7 Metadata Growth Risk

Risk:

- Preserving full relative paths increases manifest size, metadata volume, and debug output size
- Monitoring or audit views may become harder to read if full paths are emitted everywhere

Mitigation:

- Store full relative path where required for correctness
- Avoid duplicating the same long path in unnecessary metadata fields

### 9.8 Downstream Consumer Risk

Risk:

- Existing downstream tools or operators may assume all files for a day live in a flat directory under machine/date
- After the change, automation scripts, backup jobs, or manual lookup habits may break

Mitigation:

- Review all downstream readers of `processed/`
- Update operational documentation and backup assumptions
- If necessary, provide a compatibility export or transition period

### 9.9 Unsupported File and Fallback Behavior Risk

Risk:

- Fallback copy mode when Pillow is unavailable may behave differently from WebP conversion mode
- Relative path may be preserved in one mode but not the other if implementation diverges

Mitigation:

- Use the same relative path mapping for both conversion and fallback copy flows
- Verify both code paths in tests

### 9.10 Top Risks to Treat as Release Blockers

The most important risks before rollout are:

1. Same-name files from different folders overwriting each other
2. Mixed old and new batch format incompatibility
3. Recursive scanning causing unacceptable machine-side performance regression
4. Retry, cleanup, or recovery behavior becoming less predictable after path preservation

Unsafe archive member extraction is still important, but in this internal deployment it should be treated as a basic correctness guardrail rather than the primary delivery risk.

---

## 9.11 Implementation Readiness Checklist

Before coding or rollout, confirm all of the following:

1. Staged layout design prevents same-name collisions
2. Manifest schema includes canonical `relative_path`
3. Zip member paths preserve the same canonical `relative_path`
4. Worker rejects absolute and escaping paths
5. Worker supports both `flat` and `relative_tree` if mixed deployment is expected
6. Retry, inflight recovery, and cleanup are tested with nested paths
7. Recursive scan performance has been measured on realistic directory trees
8. Downstream consumers of `processed/` have been identified and reviewed

### 9.12 Performance and Stability Checklist

The implementation should not be accepted until the following are checked:

1. Recursive scan time is measured against realistic machine-side directory trees
2. CPU and disk IO increase from recursive scanning are within acceptable limits
3. Staging and cleanup continue to behave predictably with nested directories
4. Same-name files from different folders remain distinct through retries and restart recovery
5. Worker output throughput with nested directories is still acceptable under production-like load
6. Flat legacy batches and path-preserving batches can coexist safely if rollout is staged

---

## 10. Acceptance Criteria

The change is complete only when all of the following are true:

1. Machine client discovers images inside nested subfolders under `image_root`
2. Zip archives preserve each file's relative path under `image_root`
3. Manifest records preserve relative path data
4. Server accepts and queues these batches without regression
5. Worker restores the relative path under `processed/<machine>/`
6. Duplicate filenames in different subfolders do not overwrite each other
7. Retry, recovery, and cleanup still behave correctly
8. Path traversal entries are rejected safely

---

## 11. Verification Plan

### 11.1 Test Input Structure

Prepare:

```text
D:/B07-01/
  LOT001/
    NG/
      img001.jpg
      info001.png
    OK/
      img002.jpg
  LOT002/
    NG/
      img001.jpg
```

### 11.2 Expected Machine-Side Behavior

- All four files are discovered
- Both `img001.jpg` files are treated as distinct files
- Batch manifest preserves each relative path

### 11.3 Expected Server-Side Output

```text
processed/MC01/B07-01/LOT001/NG/img001.webp
processed/MC01/B07-01/LOT001/NG/info001.webp
processed/MC01/B07-01/LOT001/OK/img002.webp
processed/MC01/B07-01/LOT002/NG/img001.webp
```

### 11.4 Regression Checks

- ACK behavior unchanged
- backup server behavior unchanged
- file queue and worker retry unchanged
- dashboard image-flow data still works

---

## 12. Recommended Implementation Order

1. Update machine-side recursive scan and staged layout
2. Update manifest and zip entry structure
3. Update worker output mapping and path validation
4. Add compatibility handling if mixed old/new batches must coexist
5. Add verification cases and update documentation

---

## 13. Recommendation

The recommended implementation is:

- Recursively scan under `image_root`
- Preserve the full relative path from `image_root`
- Store that relative path in both zip entries and manifest
- Restore that relative path under the existing machine output root

This approach best matches the real production folder structure and avoids losing batch, NG/OK, and image grouping semantics.
