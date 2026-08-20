# Course Courier — Sprint 3 specification

## Purpose

Sprint 3 adds optional, declared Jupytext pair validation and staged-only normalization for exported Jupyter notebooks. The private authoring tree remains unchanged: Markdown is never exported merely because it is a notebook source, and notebook outputs or execution counts are never removed from source files.

## Manifest extension

Version 1 manifests may include one or more optional `[[notebook]]` tables.

```toml
[[notebook]]
notebook = "lectures/01b/01b-reproducible-discovery.ipynb"
markdown = "lectures/01b/01b-reproducible-discovery.md"
```

`notebook` and `markdown` are required safe relative POSIX paths under the content root. `notebook` must name exactly one `[[export]].source`, must end in `.ipynb`, and may occur in only one notebook table. `markdown` must end in `.md`, exist as a regular non-symbolic-link file, and may occur in only one notebook table. The Markdown source need not be exported. Unknown notebook-table fields are errors.

Courses that do not declare a notebook table retain Sprint 2 byte-for-byte staging behaviour for their exported notebooks.

## Pair validation

For every declared pair, Course Courier reads the Markdown with Jupytext and reads the private notebook with nbformat. It clears execution counts and outputs from both in-memory notebooks, validates their notebook structure, ignores generated cell IDs and Jupytext's format-specific `text_representation` metadata, and compares canonical structural JSON. Any difference is a synchronization error.

`build` and `verify` always perform this non-mutating check. They do not run a command that rewrites a private notebook. This is stricter and safer than a CI-only mutation check: a pair must already be synchronized before it can publish.

## Staged normalization

After a declared notebook pair passes validation, `build` creates its staged notebook from the private `.ipynb` source, clears each code cell's `execution_count` and `outputs`, validates it with nbformat, and writes a canonical nbformat serialization. The source file is not modified. Non-notebook exports retain Sprint 2 byte-preserving copy semantics.

`verify` recreates the normalized notebook bytes from the current private source and compares the staged notebook's size and SHA-256 digest to those expected bytes. Thus it detects source drift, staged notebook tampering, and a stale or differently normalized staged output.

## Inventory extension

Sprint 2 inventory fields remain unchanged. When a manifest declares notebook pairs, the inventory additionally includes a destination-sorted `notebook_exports` array. Each entry contains `source`, `markdown`, `destination`, `size_bytes`, and `sha256`; the size and hash describe the normalized staged notebook, not the private source notebook.

```json
{
  "notebook_exports": [
    {
      "destination": "course/lectures/01b/01b.ipynb",
      "markdown": "lectures/01b/01b.md",
      "sha256": "lowercase-hex-digest",
      "size_bytes": 12345,
      "source": "lectures/01b/01b.ipynb"
    }
  ]
}
```

The array is omitted when no notebook pairs are declared. Build and verify must emit identical canonical inventories for an unchanged source and staged tree.

## Dependencies

Sprint 3 adds `jupytext` and `nbformat` as direct runtime dependencies, managed and locked with uv. Jupytext parses declared Markdown notebooks; nbformat validates and serializes notebook JSON. No subprocess invocation is used.

## Acceptance tests

Tests prove that a synchronized declared pair builds a valid normalized notebook; source notebook bytes remain unchanged; outputs and execution counts are absent only from the staged copy; inventory hashes describe the staged notebook; stale pairs, malformed Markdown, malformed notebooks, duplicate declarations, and unexported notebook declarations fail; and verify rejects a changed normalized staged notebook.

## Definition of done

Sprint 3 is complete when declared Jupytext pairs and staged-only notebook normalization meet this specification, all tests pass, and an existing manifest without notebook tables continues to build and verify unchanged.
