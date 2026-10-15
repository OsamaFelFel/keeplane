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
