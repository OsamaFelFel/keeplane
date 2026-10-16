# PostgreSQL driver packages

The default preview image has no PostgreSQL driver. The optional `postgres`
Docker target installs Psycopg 3.3.6 and its unmodified, source-built C extension,
both LGPL-3.0-only, as independently replaceable Python distributions. The
extension dynamically links to Alpine `libpq` 18.6-r0. Compiler tools remain in
the build stage. This avoids bundling a second OpenSSL or other native client
stack from a binary wheel.

The original driver license is retained in `psycopg-3.3.6.txt`. The two JSON
records identify the exact upstream source archives and hashes. The image
contains both corresponding source archives at `/usr/share/keeplane/sources/`,
license records at `/usr/share/keeplane/licenses/` and installed-package/native
link information at `/usr/share/keeplane/postgres-package.json`. Installed wheel
metadata also retains its upstream license files. Preserve these when
redistributing the package, allow replacement of the installed drivers and
retain modification and relinking rights required by their licenses.

The pure-Python requirement file remains available for environments where
library discovery is configured. The minimal Alpine runtime uses the supported
C extension because its pure driver cannot find the versioned libpq without
additional build tools. The pinned libpq package adds only libpq to the selected
base; its shared dependencies are the base's OpenSSL and musl.

The build records are not a complete license/source inventory or security
clearance for the Python/Alpine base image. Native package source, Alpine patches
and all required base-image notices still need to accompany the final release.
The disposable integration fixture's binary wheels have a separate inventory.
Community and Enterprise application licenses are unchanged.

## Collect pinned base sources

`runtime-sources.json` pins the current Python base build recipe, Python source
and 20 Alpine package recipes, including optional libpq. With Python 3.10 or
newer and network access, collect them into a fresh directory outside Git:

```sh
python3 components/control-plane/collect_runtime_sources.py \
  --output /tmp/keeplane-runtime-sources
```

The collector verifies recipe hashes and their literal source checksums. It
keeps archives, Alpine patches, configuration and public keys. Original notices
remain inside verified archives; recipes are never executed or archives extracted.
Downloads have a four-minute
deadline, three workers, a 64 MiB file limit and a 256 MiB total limit. Failures
appear in `collection.json` and return a nonzero exit status. This covers the
pinned source inputs; complete binary, bundled-code and notice review remains
separate release work. Keep downloaded files and reports outside Git.
