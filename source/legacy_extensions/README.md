# Legacy Extensions

This directory is reserved for extensions that have been retired from the main
`source/extensions` tree but may still be useful as reference implementations or
temporary compatibility code.

Premake scans this directory when it exists and includes any nested
`premake5.lua` files it finds. Keeping the scan optional lets the repository
build cleanly when this directory contains only this README, while still making
it easy to move an extension here later.

When retiring an extension:

- Move the extension directory from `source/extensions` to
  `source/legacy_extensions`.
- Remove the extension from active apps, bundles, dependency lists, tests, and
  documentation unless that legacy behavior is still intentionally supported.
- Leave a clear note in the extension's docs or changelog explaining why it was
  retired and what replaces it, if anything.
- Verify that the top-level build still succeeds with the retired extension in
  this directory.

Do not add new active development here. New and supported extensions belong in
`source/extensions`.
