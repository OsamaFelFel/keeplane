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

test('artwork copied into the source keeps its notice and names every file it is in', () => {
  const records = readdirSync(new URL('licenses/', root)).filter(name => name.endsWith('.json'))
    .map(name => JSON.parse(readFileSync(new URL(`licenses/${name}`, root), 'utf8')))
    .filter(record => record.copied_into)
  const lucide = records.find(record => record.name === 'lucide-static')
  assert.ok(lucide, 'Missing the Lucide record')
  for (const record of records) {
    const text = readFileSync(new URL(`licenses/${record.name}-${record.version}.txt`, root))
    assert.equal(createHash('sha256').update(text).digest('hex'), record.sha256)
    assert.ok(notice.includes(`## Copied artwork: ${record.name} ${record.version}, ${record.license}`))
    assert.ok(notice.includes(text.toString('utf8')) && notice.includes(record.source_url) && notice.includes(record.modifications))
    for (const file of record.copied_into) {
      assert.match(readFileSync(new URL(file, root), 'utf8'), new RegExp(`licenses/${record.name}-${record.version}\\.json`), `${file} doesn't name its source`)
    }
  }
  // Every source file that says it draws a Lucide icon is listed in the record.
  const sources = readdirSync(new URL('src/', root), { recursive: true })
    .filter(name => /\.(ts|tsx)$/.test(name))
    .filter(name => /\bLucide\b/.test(readFileSync(new URL(`src/${name}`, root), 'utf8')))
    .map(name => `src/${name.split('\\').join('/')}`)
  assert.deepEqual(sources.sort(), [...lucide.copied_into].sort())
})

test('the distributed font notice remains verbatim', () => {
  assert.deepEqual(readFileSync(new URL('dist/fonts/LICENSE.txt', root)), readFileSync(new URL('public/fonts/LICENSE.txt', root)))
})
