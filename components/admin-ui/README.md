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
