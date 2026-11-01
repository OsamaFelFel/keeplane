import { expect, test, type Page } from '@playwright/test'
import { firstAdminPassword } from './credentials'

// Cases: offline-assets-cases.md. Every request that leaves the Keeplane origin is
// blocked and recorded, so a missing local font or asset fails here.

const plexFiles = ['IBMPlexMono-Regular.woff2', 'IBMPlexSans-Medium.woff2', 'IBMPlexSans-Regular.woff2', 'IBMPlexSans-SemiBold.woff2']

async function keeplaneOnly(page: Page) {
  const origin = new URL(test.info().project.use.baseURL ?? 'http://127.0.0.1:3000').origin
  const blocked: string[] = []
  const failed: string[] = []
  const fonts = new Map<string, { status: number; type: string }>()
  await page.context().route(url => url.origin !== origin, route => {
    blocked.push(route.request().url())
    return route.abort('blockedbyclient')
  })
  await page.context().routeWebSocket(url => url.host !== new URL(origin).host, ws => {
    blocked.push(ws.url())
    return ws.close()
  })
  page.on('requestfailed', request => {
    if (new URL(request.url()).origin === origin) failed.push(`${request.url()} ${request.failure()?.errorText}`)
  })
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.origin === origin && /\.(woff2?|ttf|otf)$/.test(url.pathname)) {
      fonts.set(url.pathname.split('/').pop()!, { status: response.status(), type: response.headers()['content-type'] ?? '' })
    }
    if (url.origin === origin && /^\/(app\/)?(assets|fonts)\//.test(url.pathname) && response.status() !== 200) {
      failed.push(`${response.url()} ${response.status()}`)
    }
  })
  return { blocked, failed, fonts }
}

async function renderedFamilies(page: Page, selector: string) {
  // Chromium reports the font actually used to draw the node's text.
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('DOM.enable')
  await cdp.send('CSS.enable')
  const { root } = await cdp.send('DOM.getDocument')
  const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector })
  const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })
  await cdp.detach()
  return fonts
}

// PostScript names inside the bundled files (IBMPlexSans-Regular.woff2 is "IBMPlexSans").
// The design system sets body text in 400, field labels and secondary buttons in 500,
// titles and the primary button in 600.
const drawnBy = { 400: 'IBMPlexSans', 500: 'IBMPlexSans-Medm', 600: 'IBMPlexSans-SmBld' } as const
type Weight = keyof typeof drawnBy

async function expectPlex(page: Page, drawn: [selector: string, weight: Weight][]) {
  await page.evaluate(() => document.fonts.ready)
  const state = await page.evaluate(selectors => {
    const style = (selector: string) => getComputedStyle(document.querySelector(selector)!)
    const first = (selector: string) => style(selector).fontFamily.split(',')[0].replace(/["']/g, '').trim()
    const faces = [...document.fonts].map(face => `${face.family.replace(/["']/g, '')} ${face.weight} ${face.status}`).sort()
    return { html: first('html'), nodes: selectors.map(selector => ({ family: first(selector), weight: Number(style(selector).fontWeight) })), faces }
  }, drawn.map(([selector]) => selector))
  expect(state.html).toBe('IBM Plex Sans')
  for (const [index, [selector, weight]] of drawn.entries()) {
    expect(state.nodes[index], selector).toEqual({ family: 'IBM Plex Sans', weight })
    // The page's own text loads the Sans file for each weight it draws, without help.
    expect(state.faces).toContain(`IBM Plex Sans ${weight} loaded`)
    const used = await renderedFamilies(page, selector)
    expect(used.length, selector).toBeGreaterThan(0)
    for (const font of used) {
      // The font file's own name table says which Plex face drew the text, so a weight
      // drawn with a neighbouring file or a synthesized face fails here.
      expect(font.familyName).toMatch(/^IBM Plex Sans/)
      expect(font.isCustomFont).toBe(true)
      expect(font.postScriptName, selector).toBe(drawnBy[weight])
    }
  }
  // Faces a page does not draw (code text, or regular text on sign-in) are loaded on
  // request, so every declared face must load from Keeplane.
  const faces = await page.evaluate(async () => {
    await Promise.all([
      ...['400', '500', '600'].map(weight => document.fonts.load(`${weight} 16px "IBM Plex Sans"`)),
      document.fonts.load('16px "IBM Plex Mono"'),
    ])
    return [...document.fonts].map(face => `${face.family.replace(/["']/g, '')} ${face.weight} ${face.status}`).sort()
  })
  expect(faces).toEqual(['IBM Plex Mono 400 loaded', 'IBM Plex Sans 400 loaded', 'IBM Plex Sans 500 loaded', 'IBM Plex Sans 600 loaded'])
}

function expectInside(record: Awaited<ReturnType<typeof keeplaneOnly>>) {
  expect(record.blocked, 'requests that left Keeplane').toEqual([])
  expect(record.failed, 'Keeplane assets that failed').toEqual([])
  expect([...record.fonts.keys()].sort()).toEqual(plexFiles)
  for (const [name, font] of record.fonts) {
    expect(font.status, name).toBe(200)
    expect(font.type, name).toMatch(/^font\/woff2|^application\/octet-stream/)
  }
}

for (const width of [1280, 320]) {
  test(`OFF-UI-01: sign-in loads in IBM Plex with nothing from outside Keeplane at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    const record = await keeplaneOnly(page)
    await page.goto('/sign-in')
    await expect(page.getByRole('heading', { name: 'Sign in to Keeplane' })).toBeVisible()
    await expectPlex(page, [['h1', 600], ['label', 500], ['button[type=submit]', 600]])
    expectInside(record)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })

  test(`OFF-UI-02: admin pages load in IBM Plex with nothing from outside Keeplane at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    const record = await keeplaneOnly(page)
    await page.goto('/sign-in')
    await page.getByLabel('Username').fill('first-admin')
    await page.getByLabel('Password', { exact: true }).fill(firstAdminPassword())
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Users', exact: true })).toBeVisible()
    await page.goto('/app/models')
    await expect(page.getByRole('heading', { name: 'Models and routing', exact: true })).toBeVisible()
    await expectPlex(page, [['h1', 600], ['.keeplane-page-heading p', 400], ['main.keeplane-content button', 500]])
    expectInside(record)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
