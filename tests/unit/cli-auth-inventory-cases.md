# Optional sign-in package inventory cases

`test_cli_auth_inventory.py` uses synthetic wheel/cache files without network
access, package installation or archive extraction.

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

Actual source/notice collection is a separate maintainer command. Passing these
checks does not close bundled native-code provenance or release approval.
