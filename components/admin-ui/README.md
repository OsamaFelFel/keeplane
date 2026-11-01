# Admin UI

The React and TypeScript application uses Vite, React Router and shadcn/ui.

- `src/app/`: application shell and API client.
- `src/features/`: sign-in, Users, Models, Data classes, Audit and Editions.
- `src/components/ui/`: shared shadcn controls.
- `src/styles/`: Keeplane theme and shared layouts.
- `public/fonts/`: locally served fonts and their license.

Run `npm ci`, then `npm run build`, `npm run lint` or `npm run test:unit` here.
Tests live in the repository's `tests/` directory. Start the complete application
with `python3 deploy/local/up.py` from the repository root. `npm run dev` starts
Vite with API requests proxied to the local application.

Production builds retain original bundled dependency notices in
`dist/assets/THIRD_PARTY_LICENSES.txt`, served at
`/app/assets/THIRD_PARTY_LICENSES.txt`. Vite identifies bundled JavaScript;
the build also retains the package CSS imports' notices and separate copyright
files. Font notices remain at `/fonts/LICENSE.txt`. Run `npm run test:notices`
after building to verify the shipped text. Generated `dist/` stays out of Git.

The UI must load nothing from outside Keeplane: bundle every font and asset here
instead of linking a CDN or font service. After building, `npm run test:offline-assets`
fails on any external address not on its documented list.

`react-remove-scroll-bar` 2.3.8 omits its license file from npm. Its original
project MIT notice is retained under `licenses/` with a pinned source and hash.
That source declares 2.3.7; correspondence to the 2.3.8 release remains unresolved.
The notice records this exception and does not establish distribution clearance.
