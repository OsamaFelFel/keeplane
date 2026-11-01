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

function builtCss() {
  return readdirSync(new URL('assets/', dist)).filter(name => name.endsWith('.css'))
    .map(name => readFileSync(new URL(`assets/${name}`, dist), 'utf8')).join('\n')
}

function fontFaces(css) {
  return [...css.matchAll(/@font-face\s*{([^}]*)}/g)].map(([, body]) => ({
    family: body.match(/font-family:\s*["']?([^;"']+)/)?.[1],
    weight: body.match(/font-weight:\s*(\d+)/)?.[1] ?? '400',
    src: [...body.matchAll(/url\(\s*["']?([^"')]+)/g)].map(match => match[1]),
  }))
}

// The weights the design system's text styles use (product/design/system/tokens.json):
// Sans 400 body, 500 field and navigation labels, 600 titles; Mono 400 code.
const designFaces = ['IBM Plex Mono 400', 'IBM Plex Sans 400', 'IBM Plex Sans 500', 'IBM Plex Sans 600']

test('OFF-03: every stylesheet font is a bundled IBM Plex file with its licence beside it', () => {
  const css = builtCss()
  const faces = fontFaces(css)
  const declared = faces.map(face => `${face.family} ${face.weight}`).sort()
  assert.deepEqual(declared, designFaces)
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

test('OFF-05: every font weight the stylesheet asks for has its own bundled Plex face', () => {
  const css = builtCss()
  const faces = fontFaces(css)
  const bundled = family => new Set(faces.filter(face => face.family === family).map(face => Number(face.weight)))
  const rules = css.replace(/@font-face\s*{[^}]*}/g, '')
  // Tailwind writes font-medium as var(--font-weight-medium) and defines the token once.
  const tokens = new Map([...rules.matchAll(/--font-weight-([\w-]+):\s*(\d+)/g)].map(([, name, value]) => [name, Number(value)]))
  const weightOf = value => {
    const token = value.match(/^var\(--font-weight-([\w-]+)\)$/)?.[1]
    if (token) {
      assert.ok(tokens.has(token), `Undefined weight token: ${value}`)
      return tokens.get(token)
    }
    if (/^\d+$/.test(value)) return Number(value)
    return { normal: 400, bold: 700 }[value]
  }
  // Relative and reset values take the parent's weight, which is checked where it is
  // set; bolder from 400 or 500 asks for 700, which draws with the 600 file.
  const relative = new Set(['inherit', 'initial', 'unset', 'revert', 'revert-layer', 'bolder', 'lighter'])
  const used = new Set([400])
  for (const [, raw] of rules.matchAll(/(?<![\w-])font-weight:\s*([^;}!]+)/g)) {
    const value = raw.trim()
    if (relative.has(value)) continue
    const weight = weightOf(value)
    assert.ok(weight, `Unrecognised font weight: ${value}`)
    used.add(weight)
  }
  for (const [, raw] of rules.matchAll(/(?<![\w-])font:\s*([^;}!]+)/g)) {
    assert.ok(relative.has(raw.trim()), `Font shorthand sets a weight this check does not read: ${raw}`)
  }
  const sans = bundled('IBM Plex Sans')
  const missing = [...used].filter(weight => !sans.has(weight)).sort()
  assert.deepEqual(missing, [], `IBM Plex Sans weights used without a bundled file: ${missing.join(', ')}`)
  assert.ok(sans.has(500), 'The field-label weight 500 has its own Plex Sans file')

  // A rule that sets Plex Mono may only ask for a bundled Mono weight; the design uses regular.
  const mono = bundled('IBM Plex Mono')
  for (const [, body] of rules.matchAll(/{([^{}]*IBM Plex Mono[^{}]*)}/g)) {
    const value = body.match(/(?<![\w-])font-weight:\s*([^;}!]+)/)?.[1]?.trim()
    if (value && !relative.has(value)) assert.ok(mono.has(weightOf(value)), `IBM Plex Mono weight without a bundled file: ${value}`)
  }

  // The fonts folder ships exactly the files the stylesheet declares, plus the licence.
  const shipped = readdirSync(new URL('fonts/', dist)).filter(name => name !== 'LICENSE.txt').sort()
  const declared = [...new Set(faces.flatMap(face => face.src.map(src => src.split('/').pop())))].sort()
  assert.deepEqual(shipped, declared)
})

test('OFF-06: every font weight on the CLI sign-in pages has its own bundled Plex face', () => {
  const names = readdirSync(templates).filter(name => name.endsWith('.html'))
  const html = names.map(name => readFileSync(new URL(name, templates), 'utf8')).join('\n')
  const css = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(([, body]) => body).join('\n')
  assert.ok(css.length > 0, 'The CLI sign-in pages have no stylesheet')
  const faces = fontFaces(css)
  const declared = new Set(faces.filter(face => face.family === 'IBM Plex Sans').map(face => Number(face.weight)))
  const rules = [...css.replace(/@font-face\s*{[^}]*}/g, '').matchAll(/([^{}]+){([^{}]*)}/g)]
    .map(([, selector, body]) => ({ selectors: selector.split(',').map(part => part.trim()), body }))
  const relative = new Set(['inherit', 'initial', 'unset', 'revert', 'revert-layer', 'bolder', 'lighter'])
  const named = { normal: 400, bold: 700 }
  const used = new Set([400])
  const weighted = new Set()
  const weightOf = value => /^\d+$/.test(value) ? Number(value) : named[value]
  for (const { selectors, body } of rules) {
    const values = []
    const weight = body.match(/(?<![\w-])font-weight:\s*([^;}!]+)/)?.[1]?.trim()
    if (weight) values.push(weight)
    // The font shorthand resets the weight to normal unless it starts with one.
    const shorthand = body.match(/(?<![\w-])font:\s*([^;}!]+)/)?.[1]?.trim()
    if (shorthand && !relative.has(shorthand)) {
      const first = shorthand.split(/\s+/)[0]
      values.push(weightOf(first) ? first : 'normal')
    }
    for (const value of values) {
      if (relative.has(value)) continue
      assert.ok(weightOf(value), `Unrecognised CLI page font weight: ${value}`)
      used.add(weightOf(value))
    }
    if (values.length) selectors.forEach(selector => weighted.add(selector))
  }
  // Headings and strong text are bold (700) by default unless the page sets their weight.
  for (const [, tag] of html.matchAll(/<(h[1-6]|strong|b|th)\b/g)) {
    if (!weighted.has(tag)) used.add(700)
  }
  const missing = [...used].filter(weight => !declared.has(weight)).sort()
  assert.deepEqual(missing, [], `CLI page weights used without a bundled Plex file: ${missing.join(', ')}`)
  assert.ok(declared.has(500), 'The CLI pages declare the medium Plex file for labels and buttons')
  const label = rules.find(rule => rule.selectors.includes('label'))?.body.match(/font-weight:\s*(\d+)/)?.[1]
  assert.equal(label, '500', 'Field labels use the design weight 500')

  // The CLI code is set in IBM Plex Mono regular, the design's code style.
  assert.deepEqual(faces.map(face => `${face.family} ${face.weight}`).sort(),
    ['IBM Plex Mono 400', 'IBM Plex Sans 400', 'IBM Plex Sans 500', 'IBM Plex Sans 600'])
  const mono = faces.filter(face => face.family === 'IBM Plex Mono')
  assert.deepEqual(mono.flatMap(face => face.src), ['/fonts/IBMPlexMono-Regular.woff2'])
  const monoRules = rules.filter(rule => /font-family:\s*["']?IBM Plex Mono/.test(rule.body))
  assert.ok(monoRules.some(rule => rule.selectors.includes('code')), 'CLI code text is set in IBM Plex Mono')
  for (const rule of monoRules) {
    const weight = rule.body.match(/(?<![\w-])font-weight:\s*([^;}!]+)/)?.[1]?.trim()
    assert.ok(!weight || weight === '400', `IBM Plex Mono weight without a bundled file: ${weight}`)
  }
  for (const [, tag] of html.matchAll(/<(code|pre|kbd|samp)\b/g)) {
    assert.ok(monoRules.some(rule => rule.selectors.includes(tag)), `<${tag}> on the CLI pages is not set in IBM Plex Mono`)
  }
})
