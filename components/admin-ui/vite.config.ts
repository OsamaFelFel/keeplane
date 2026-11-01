import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'

const metadataFile = '.vite/bundled-licenses.json'

function bundledNotices(): Plugin {
  return {
    name: 'keeplane:bundled-notices',
    generateBundle: {
      order: 'post',
      handler(_, bundle) {
        const metadata = bundle[metadataFile]
        if (!metadata || metadata.type !== 'asset' || typeof metadata.source !== 'string') {
          this.error('Bundled license metadata is unavailable')
        }
        const packages = JSON.parse(metadata.source) as { name: string; version: string }[]
        // Tailwind processes these CSS imports before Vite examines JS chunks.
        const css = readFileSync(new URL('./src/index.css', import.meta.url), 'utf8')
        for (const [, name] of css.matchAll(/@import\s+["']([^"']+)["']/g)) {
          if (name.startsWith('.')) continue
          const pkg = JSON.parse(readFileSync(new URL(`./node_modules/${name}/package.json`, import.meta.url), 'utf8'))
          if (!packages.some(entry => entry.name === pkg.name)) packages.push(pkg)
        }
        let text = '# Bundled dependency notices\n\nFont notices: /fonts/LICENSE.txt\n'
        for (const { name, version } of packages.sort((a, b) => a.name.localeCompare(b.name))) {
          const folder = new URL(`./node_modules/${name}/`, import.meta.url)
          const pkg = JSON.parse(readFileSync(new URL('package.json', folder), 'utf8'))
          if (pkg.version !== version) this.error(`License version mismatch for ${name}`)
          text += `\n## ${name} - ${version} (${pkg.license})\n`
          const files = readdirSync(folder, { withFileTypes: true }).filter(file =>
            file.isFile() && /^(licen[cs]e|copying|notice|copyright)/i.test(file.name))
          if (files.length) {
            for (const file of files) text += `\n${readFileSync(new URL(file.name, folder), 'utf8')}\n`
          } else {
            const record = JSON.parse(readFileSync(new URL(`./licenses/${name}-${version}.json`, import.meta.url), 'utf8'))
            const notice = readFileSync(new URL(`./licenses/${name}-${version}.txt`, import.meta.url))
            if (record.name !== name || record.version !== version || createHash('sha256').update(notice).digest('hex') !== record.sha256) {
              this.error(`Invalid retained license notice for ${name}`)
            }
            text += `\n${record.correspondence}\nSource: ${record.source_url}\n\n${notice.toString('utf8')}\n`
          }
        }
        // Artwork copied into the source, such as an icon drawn inline, isn't an
        // npm dependency; its record names the files it was copied into.
        for (const file of readdirSync(new URL('./licenses/', import.meta.url)).filter(name => name.endsWith('.json')).sort()) {
          const record = JSON.parse(readFileSync(new URL(`./licenses/${file}`, import.meta.url), 'utf8'))
          if (!record.copied_into) continue
          const notice = readFileSync(new URL(`./licenses/${record.name}-${record.version}.txt`, import.meta.url))
          if (createHash('sha256').update(notice).digest('hex') !== record.sha256) {
            this.error(`Invalid copied artwork notice for ${record.name}`)
          }
          // Not "name - version (": that heading form lists bundled npm packages.
          text += `\n## Copied artwork: ${record.name} ${record.version}, ${record.license}\n`
          text += `\n${record.copied}\nModifications: ${record.modifications}\nSource: ${record.source_url} (${record.source_file})\n\n${notice.toString('utf8')}\n`
        }
        delete bundle[metadataFile]
        this.emitFile({ type: 'asset', fileName: 'assets/THIRD_PARTY_LICENSES.txt', source: text })
      },
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: '/app/',
  plugins: [react(), tailwindcss(), bundledNotices()],
  build: { license: { fileName: metadataFile } },
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  server: { proxy: { '/api': 'http://127.0.0.1:3000', '/sign-out': 'http://127.0.0.1:3000', '/fonts': 'http://127.0.0.1:3000' } },
})
