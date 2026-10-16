# Optional sign-in package inventory cases

`test_cli_auth_inventory.py` uses synthetic wheel/cache files without network
access, package installation or unpacking archive trees.

- Offline collection preserves source and notice bytes, reports native review
  incomplete, and refuses to overwrite a previous output directory.
- A changed wheel is refused before output or downloads begin.
- Absolute, parent-relative, backslash and empty notice paths cannot write
  outside the output directory.
- A changed source leaves a failed inventory and no accepted archive.
- The pinned package/version/wheel graph must match the requirement file;
  duplicate or missing package records are refused.
- Native source URL, checksum and version must match the original SBOM in the
  verified wheel before collection starts. Original build records are retained.
- Only bounded regular licence files with the pinned checksum are copied from
  verified native archives; a mismatch retains failure and writes no notice.
- Rust registry entries must cover the original SBOM exactly, including excluded
  entries. Duplicate, missing, changed-scope/checksum/URL and workspace drift
  stop collection before downloads.
- The verified Python source archive must contain the exact Cargo.lock and its
  complete package/checksum mapping. A changed lock leaves a failed inventory
  and copies no Rust notices.
- Original Cargo licence strings, including legacy forms, stay unchanged. A
  changed declaration prevents that crate's notice from being accepted.

Actual source/notice collection is a separate maintainer command. Passing these
checks does not close bundled native-code provenance or release approval.
