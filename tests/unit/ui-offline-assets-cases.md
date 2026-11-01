# Web UI served from inside Keeplane

**Edition:** Open Source; the same rule applies to Enterprise.
**Spec:** 002 Self-hosting, ST2 "The web UI loads from inside" (ADR 009).

These checks read the production build in `components/admin-ui/dist/` and the
CLI sign-in page templates. Build first, then run from `components/admin-ui`:
`npm run build && npm run test:offline-assets`.

| ID | Plain-English check | Expected result |
| --- | --- | --- |
| OFF-01 | Look through the page, every script and stylesheet, and the CLI sign-in pages for web addresses. | Every full address is on the short list below; no address starts with `//`. Anything else fails with the file and address. |
| OFF-02 | Read the page's script and stylesheet links. | Each one points to a built file under `/app/assets/` that exists; no source map points outside. |
| OFF-03 | Read the stylesheet's font declarations. | Exactly the design system's faces: IBM Plex Sans regular (400), medium (500) and semibold (600) and IBM Plex Mono regular (400), each a bundled file under `/app/fonts/`; the IBM Plex SIL Open Font License 1.1 notice ships beside them. |
| OFF-04 | Read the CLI sign-in pages' fonts and links. | They use only the bundled Plex files under `/fonts/` and load no outside script, stylesheet, image or frame. |
| OFF-05 | Read every font weight the stylesheet asks for, including Tailwind weight tokens such as `font-medium`. | Each weight has its own bundled IBM Plex Sans file, so none is drawn with a neighbouring file or made bolder by the browser; any rule that sets Plex Mono asks only for a bundled Mono weight; the fonts folder holds exactly the declared files and the licence. An unknown weight value fails with its text. |
| OFF-06 | Read every font weight the CLI sign-in pages ask for, including the `font` shorthand and the bold that headings and strong text get by default. | Each weight has its own declared Plex file on those pages: regular (400) for text, medium (500) for field labels and secondary buttons, semibold (600) for the title, strong text and the primary button. Field labels use 500, as in the design system. |

## Allowed addresses

These appear as text and are never requested by the browser. A dependency
upgrade that changes one fails OFF-01 until it is reviewed and listed in
`ui-offline-assets.test.mjs`.

| Address | Why it appears |
| --- | --- |
| `http://www.w3.org/2000/svg`, `…/1999/xlink`, `…/XML/1998/namespace`, `…/1998/Math/MathML` | XML namespace names used by React and the logo. |
| `https://tailwindcss.com` | Licence comment at the top of the stylesheet. |
| `https://react.dev/errors/`, `https://reactrouter.com/…picking-a-router.` | Text inside developer error messages. |
| `json-schema.org` schema names (three drafts) | Names written into a JSON Schema by the form library. |
| `http://localhost`, `http://[${e}]` | Bases the router and form library use to parse text as an address. |
| `http://qwen:8080` | Example runner address shown in the Models form. |

The [browser cases](../browser/offline-assets-cases.md) prove at run time that
nothing leaves Keeplane.
