# Personal-data detection: components, notices and sources

Personal-data detection is optional and off by default. Only the `detection`
Docker target installs it; the default preview, `postgres` and sign-in targets
are unchanged. Both editions use the same components.

`requirements-detection.txt` pins 50 Python wheels for Linux musl x86-64
CPython 3.13 and the spaCy `en_core_web_lg` 3.8.0 model wheel, each by SHA-256.
They are the versions measured for the release-1 detection bar (Presidio
Analyzer 2.2.364, spaCy 3.8.18); `packaging` stays at the app's own 26.1. `personal-data-detection.json` records, for
every component, its declared licence, the exact wheel and its hash, the
matching published source archive and its hash, the hash of every original
notice file inside the wheel and any bundled native library.

## Licence terms accepted for both editions

The owner accepted these obligations on 1 November 2026. Keep them when
redistributing an image built from the `detection` target:

- **Bundled native libraries.** numpy's wheel bundles OpenBLAS, `libgfortran`
  and `libgcc_s` (GPL-3.0 with the GCC Runtime Library Exception) and
  `libquadmath` (LGPL-2.1). The musl wheels of numpy, spaCy, thinc, preshed and
  pydantic-core also bundle `libstdc++` and `libgcc_s` under the same runtime
  exception. Review on 1 November 2026 confirmed these are the same GCC
  Runtime Library Exception terms as numpy's bundled libraries, so the owner's
  acceptance covers them. The libraries are unmodified and dynamically linked,
  so they can be replaced. Offer their corresponding source (below) and keep the original
  notices.
- **MPL-2.0.** certifi, tqdm (MPL-2.0 and MIT) and the public-suffix list
  bundled in tldextract are MPL-2.0. They are unmodified; their source archives
  are listed in the inventory. Offer them with the image.
- **Presidio's MIT notice.** The published Presidio Analyzer wheel has no
  licence file. `presidio-analyzer-2.2.364-LICENSE.txt` is the MIT licence from
  the matching upstream tag; ship it with the image.
- **Model training data.** `en_core_web_lg` is MIT. It was trained on
  OntoNotes 5, licensed to Explosion commercially, and uses WordNet 3.0 under
  the WordNet licence. The model wheel keeps these terms in `LICENSE` and
  `LICENSES_SOURCES`; keep both.

## Source offer

Every Python component's exact source archive is named, with its URL and
SHA-256, in `personal-data-detection.json`. The model's source is its upstream
release page. Recipients of an image built from the `detection` target can get
these sources from those addresses; keep this offer, the inventory and the
notices with any image you redistribute. The `detection` image copies this
file, the inventory and the supplemental Presidio notice to
`/usr/share/keeplane/licenses/`.

The native libraries' own build sources (GCC runtime and OpenBLAS) follow the
same open item as the base image in [README.md](README.md): a complete binary
inventory remains release work.

## Rebuild the pins

With network access, in an empty directory outside the repository:

```sh
pip download --no-deps --only-binary=:all: \
  --platform musllinux_1_2_x86_64 --platform musllinux_1_1_x86_64 \
  --python-version 3.13 --implementation cp \
  --abi cp313 --abi abi3 --abi none \
  -r <the package versions in requirements-detection.txt> -d wheels
```

Compare every wheel's SHA-256 with the pin and the inventory before changing
either. A new version needs the release-1 bar measured again.
