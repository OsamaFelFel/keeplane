// Static check that the built web UI references nothing outside Keeplane.
// Cases: ui-offline-assets-cases.md. Run `npm run build` in components/admin-ui first.
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'

const repo = new URL('../../', import.meta.url)
const dist = new URL('components/admin-ui/dist/', repo)
const templates = new URL('components/control-plane/accounts/templates/accounts/', repo)

// Absolute URLs that may appear in served UI text because no browser requests them.
// Each entry is an exact string; a dependency upgrade that changes one must be reviewed here.
const allowed = new Map([
  ['http://www.w3.org/2000/svg', 'SVG XML namespace identifier'],
  ['http://www.w3.org/1999/xlink', 'XLink XML namespace identifier'],
  ['http://www.w3.org/XML/1998/namespace', 'XML namespace identifier'],
  ['http://www.w3.org/1998/Math/MathML', 'MathML XML namespace identifier'],
  ['https://tailwindcss.com', 'Tailwind licence comment in the stylesheet'],
  ['https://react.dev/errors/', 'React production error message text'],
  ['https://reactrouter.com/en/main/routers/picking-a-router.', 'React Router error message text'],
  ['https://json-schema.org/draft/2020-12/schema', 'Zod JSON Schema $schema identifier'],
  ['http://json-schema.org/draft-07/schema#', 'Zod JSON Schema $schema identifier'],
  ['http://json-schema.org/draft-04/schema#', 'Zod JSON Schema $schema identifier'],
  ['http://localhost', 'React Router base for parsing relative paths, never requested'],
  ['http://[${e}]', 'Zod IPv6 check parses a URL string, never requested'],
  ['http://qwen:8080', 'Models form placeholder for a runner address on the customer network'],
])

const absoluteUrl = /\b(?:https?|wss?|ftp):\/\/[^\s"'`)<>\\]+/g
const protocolRelative = /(?:url\(\s*["']?|(?:src|href|action|srcset)\s*=\s*["']?|@import\s+["']?)\/\/[^\s"'`)<>\\]*/gi

function servedFiles() {
  assert.ok(existsSync(new URL('index.html', dist)), 'Build the admin UI first: npm run build in components/admin-ui')
  const files = [new URL('index.html', dist)]
  for (const name of readdirSync(new URL('assets/', dist))) {
    if (/\.(js|css|svg|html|json|map)$/.test(name)) files.push(new URL(`assets/${name}`, dist))
  }
  for (const name of readdirSync(templates)) {
    if (name.endsWith('.html')) files.push(new URL(name, templates))
  }
  return files
}

const relative = url => url.href.slice(repo.href.length)

test('OFF-01: served UI files contain no external URL outside the allow-list', () => {
  const found = []
  for (const file of servedFiles()) {
    const text = readFileSync(file, 'utf8')
    for (const [url] of text.matchAll(absoluteUrl)) {
      if (!allowed.has(url)) found.push(`${relative(file)}: ${url}`)
    }
    for (const [match] of text.matchAll(protocolRelative)) found.push(`${relative(file)}: ${match}`)
  }
  assert.deepEqual(found, [], 'Unexpected external references; bundle the asset or document why it is never requested')
})

test('OFF-02: the page loads only Keeplane-served scripts and stylesheets', () => {
  const html = readFileSync(new URL('index.html', dist), 'utf8')
  const references = [...html.matchAll(/\b(?:src|href)\s*=\s*["']([^"']+)["']/g)].map(match => match[1])
  assert.ok(references.length > 0)
  for (const reference of references) {
    assert.match(reference, /^\/app\/assets\/[\w.-]+\.(js|css)$/, `Unexpected page reference: ${reference}`)
    assert.ok(existsSync(new URL(reference.slice('/app/'.length), dist)), `Missing built file: ${reference}`)
  }
  for (const file of readdirSync(new URL('assets/', dist))) {
    if (!/\.(js|css)$/.test(file)) continue
    const text = readFileSync(new URL(`assets/${file}`, dist), 'utf8')
    assert.doesNotMatch(text, /sourceMappingURL=(?!data:)\S*:\/\//, `External source map in ${file}`)
  }
})

test('OFF-03: every stylesheet font is a bundled IBM Plex file with its licence beside it', () => {
  const css = readdirSync(new URL('assets/', dist)).filter(name => name.endsWith('.css'))
    .map(name => readFileSync(new URL(`assets/${name}`, dist), 'utf8')).join('\n')
  const faces = [...css.matchAll(/@font-face\s*{([^}]*)}/g)].map(([, body]) => ({
    family: body.match(/font-family:\s*["']?([^;"']+)/)?.[1],
    weight: body.match(/font-weight:\s*(\d+)/)?.[1] ?? '400',
    src: [...body.matchAll(/url\(\s*["']?([^"')]+)/g)].map(match => match[1]),
  }))
  const declared = faces.map(face => `${face.family} ${face.weight}`).sort()
  assert.deepEqual(declared, ['IBM Plex Mono 400', 'IBM Plex Sans 400', 'IBM Plex Sans 600'])
  for (const face of faces) {
    assert.ok(face.src.length > 0, `${face.family} has no source`)
    for (const src of face.src) {
      assert.match(src, /^\/app\/fonts\/IBMPlex[\w-]+\.woff2$/, `Font not served by Keeplane: ${src}`)
      assert.ok(existsSync(new URL(src.slice('/app/'.length), dist)), `Missing bundled font: ${src}`)
    }
  }
  for (const [, src] of css.matchAll(/url\(\s*["']?([^"')]+)/g)) {
    assert.match(src, /^(\/app\/|data:)/, `Stylesheet reference outside Keeplane: ${src}`)
  }
  const licence = readFileSync(new URL('fonts/LICENSE.txt', dist), 'utf8')
  assert.match(licence, /SIL OPEN FONT LICENSE Version 1\.1/)
  assert.match(licence, /Copyright © 2017 IBM Corp\. with Reserved Font Name "Plex"/)
})

test('OFF-04: the CLI sign-in pages use only Keeplane-served Plex fonts', () => {
  const html = readdirSync(templates).filter(name => name.endsWith('.html'))
    .map(name => readFileSync(new URL(name, templates), 'utf8')).join('\n')
  const sources = [...html.matchAll(/url\(\s*["']?([^"')]+)/g)].map(match => match[1])
  assert.ok(sources.length > 0)
  for (const src of sources) {
    assert.match(src, /^\/fonts\/IBMPlex[\w-]+\.woff2$/, `Template font not served by Keeplane: ${src}`)
    assert.ok(existsSync(new URL(src.slice(1), dist)), `Missing bundled font: ${src}`)
  }
  assert.doesNotMatch(html, /<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=\s*["']?(?!\/)[a-z]/i)
})
