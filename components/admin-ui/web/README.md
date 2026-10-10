# Keeplane admin UI

This is the React implementation of the Open Source Users screen. It uses Vite,
shadcn/ui components, Radix, Tailwind, React Hook Form, Zod, and TanStack Table.
The theme in `src/styles/theme.css` is copied from the product design tokens.
Radix Icons supply the small set of UI icons under an MIT licence.

Run `npm ci && npm run build` in this directory, then start the Docker preview
with `python3 deploy/local/up.py` from the repository root. Open
`http://127.0.0.1:3000/users`. The preview server serves the built files and
its account API from the same origin. `npm run lint` checks the source.

The existing admin screens are still served by the older UI while they are
converted. The React navigation keeps unavailable screens disabled.
