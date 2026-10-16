import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'

const root = new URL('../../components/admin-ui/', import.meta.url)
const notice = readFileSync(new URL('dist/assets/THIRD_PARTY_LICENSES.txt', root), 'utf8')
const packages = [...notice.matchAll(/^## (.+) - ([\w.-]+) \(/gm)].map(match => match[1])

test('production output keeps the original bundled package notices', () => {
  for (const name of ['react', 'react-dom', '@radix-ui/react-icons', '@tanstack/react-table', 'tailwindcss', 'tw-animate-css', 'tslib']) {
    assert.ok(packages.includes(name), `Missing bundled package: ${name}`)
  }
  for (const name of packages) {
    const folder = new URL(`node_modules/${name}/`, root)
    for (const file of readdirSync(folder, { withFileTypes: true })) {
      if (file.isFile() && /^(licen[cs]e|copying|notice|copyright)/i.test(file.name)) {
        assert.ok(notice.includes(readFileSync(new URL(file.name, folder), 'utf8')), `Changed notice: ${name}/${file.name}`)
      }
    }
  }
  for (const name of ['typescript', 'vitest', '@testing-library/react', '@tailwindcss/vite']) {
    assert.ok(!packages.includes(name), `Unbundled build/test package: ${name}`)
  }
})

test('the npm notice omission retains explicit pinned project provenance', () => {
  const record = JSON.parse(readFileSync(new URL('licenses/react-remove-scroll-bar-2.3.8.json', root), 'utf8'))
  const text = readFileSync(new URL('licenses/react-remove-scroll-bar-2.3.8.txt', root))
  assert.equal(createHash('sha256').update(text).digest('hex'), record.sha256)
  assert.ok(notice.includes(text.toString('utf8')))
  assert.ok(notice.includes(record.source_url) && notice.includes(record.correspondence))
  assert.match(record.correspondence, /Unresolved/)
})

test('the distributed font notice remains verbatim', () => {
  assert.deepEqual(readFileSync(new URL('dist/fonts/LICENSE.txt', root)), readFileSync(new URL('public/fonts/LICENSE.txt', root)))
})
