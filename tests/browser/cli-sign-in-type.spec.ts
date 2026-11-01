import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

// Cases: cli-sign-in-type-cases.md. The CLI sign-in pages are Django templates served
// only by the optional ADR 022 trial, so each state is rendered with Django's template
// engine and served here with the bundled Plex files; every other request is blocked.

const repo = new URL('../../', import.meta.url)
const fonts = new URL('components/admin-ui/public/fonts/', repo)
const origin = 'http://cli-sign-in.test'

function python() {
  const local = fileURLToPath(new URL('.venv/bin/python', repo))
  return process.env.KEEPLANE_TEST_PYTHON ?? (existsSync(local) ? local : 'python3')
}

const states: Record<string, string> = JSON.parse(execFileSync(python(),
  [fileURLToPath(new URL('tests/support/render_cli_sign_in.py', repo))], { encoding: 'utf8' }))

async function open(page: Page, state: string, width: number) {
  await page.setViewportSize({ width, height: 800 })
  const outside: string[] = []
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin !== origin) {
      outside.push(url.href)
      return route.abort('blockedbyclient')
    }
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: states[state] })
    const font = url.pathname.match(/^\/fonts\/(IBMPlex[\w-]+\.woff2)$/)?.[1]
    if (font) return route.fulfill({ contentType: 'font/woff2', body: readFileSync(new URL(font, fonts)) })
    return route.fulfill({ status: 404 })
  })
  await page.goto(`${origin}/`)
  await page.evaluate(() => document.fonts.ready)
  return outside
}

type Style = { size: string; line: string; weight: string; family: string }

async function styleOf(page: Page, selector: string): Promise<Style[]> {
  return page.locator(selector).evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node)
    return { size: style.fontSize, line: style.lineHeight, weight: style.fontWeight,
      family: style.fontFamily.split(',')[0].replace(/["']/g, '').trim() }
  }))
}

// Text styles from the design system tokens (product/design/system/tokens.json) and the
// component specs: the card title page-title 28/36 600; body 15/22 400; "Signed in as"
// small 14/20 400 with the name at 600; field-label 14/20 500; a field error small
// 14/20; the failure message's line 15/22 600; the CLI code in code style, IBM Plex Mono
// 14/20 400; buttons and text fields 15/22, outline buttons 500 and the primary 600.
const sans = 'IBM Plex Sans'
const body = { size: '15px', line: '22px', weight: '400', family: sans }
const small = { size: '14px', line: '20px', weight: '400', family: sans }
const expected: Record<string, Style> = {
  'h1': { size: '28px', line: '36px', weight: '600', family: sans },
  'p:not([class]):not(.alert p)': body,
  '.signed-in': small,
  '.signed-in strong': { ...small, weight: '600' },
  'code': { size: '14px', line: '20px', weight: '400', family: 'IBM Plex Mono' },
  'label': { ...small, weight: '500' },
  '.field-error': small,
  '.alert p': { ...body, weight: '600' },
  'input:not([type=hidden])': body,
  'button:not([name=allow]):not([value=accept])': { ...body, weight: '500' },
  'button[name=allow], button[value=accept]': { ...body, weight: '600' },
}

for (const width of [1280, 320]) {
  for (const state of Object.keys(states)) {
    test(`CLI-TYPE-01: ${state} uses the design type scale at ${width}px`, async ({ page }) => {
      const outside = await open(page, state, width)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      let checked = 0
      for (const [selector, style] of Object.entries(expected)) {
        for (const actual of await styleOf(page, selector)) {
          expect(actual, `${state} ${selector}`).toEqual(style)
          checked += 1
        }
      }
      expect(checked).toBeGreaterThanOrEqual(2)
      const faces = await page.evaluate(() => [...document.fonts]
        .filter(face => face.status === 'loaded').map(face => `${face.family.replace(/["']/g, '')} ${face.weight}`))
      expect(faces).toContain('IBM Plex Sans 600')
      if (await page.locator('code').count()) expect(faces).toContain('IBM Plex Mono 400')
      // Every text node is checked by one of the rules above.
      const unchecked = await page.evaluate(selectors => [...document.querySelectorAll('h1, p, strong, code, label, input, button, span')]
        .filter(node => !(node instanceof HTMLInputElement && node.type === 'hidden'))
        .filter(node => !selectors.some(selector => node.matches(selector)) && !(node.matches('.field-error span')))
        .map(node => node.outerHTML.slice(0, 80)), Object.keys(expected))
      expect(unchecked).toEqual([])
      expect(outside, 'requests that left Keeplane').toEqual([])
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    })
  }

  test(`CLI-TYPE-02: controls keep the design sizes and spacing at ${width}px`, async ({ page }) => {
    await open(page, 'device-entry', width)
    const field = page.getByLabel('Code shown in your CLI')
    const label = await page.locator('label').boundingBox()
    const input = await field.boundingBox()
    expect(input!.height).toBeGreaterThanOrEqual(44)
    expect(Math.round(input!.y - (label!.y + label!.height))).toBe(6)
    const control = await field.evaluate(node => {
      const style = getComputedStyle(node)
      return { radius: style.borderRadius, edge: `${style.borderTopWidth} ${style.borderTopColor}` }
    })
    expect(control).toEqual({ radius: '6px', edge: '1px rgb(122, 133, 143)' })
    await field.focus()
    expect(await field.evaluate(node => `${getComputedStyle(node).outlineWidth} ${getComputedStyle(node).outlineStyle} ${getComputedStyle(node).outlineColor}`))
      .toBe('2px solid rgb(30, 37, 43)')

    await open(page, 'device-confirm', width)
    for (const name of ['Cancel', 'Continue']) {
      const button = page.getByRole('button', { name, exact: true })
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      expect(await button.evaluate(node => [getComputedStyle(node).paddingLeft, getComputedStyle(node).borderRadius]))
        .toEqual(['18px', '6px'])
    }
    const code = await page.locator('code').evaluate(node => {
      const style = getComputedStyle(node)
      return [style.paddingTop, style.paddingLeft, style.borderTopWidth, style.borderTopColor, style.borderRadius, style.backgroundColor]
    })
    expect(code).toEqual(['2px', '6px', '1px', 'rgb(211, 216, 221)', '4px', 'rgb(244, 245, 246)'])
    const card = await page.locator('.card').evaluate(node => ({ width: node.getBoundingClientRect().width,
      padding: getComputedStyle(node).paddingTop, radius: getComputedStyle(node).borderRadius }))
    expect(card).toEqual({ width: Math.min(400, width - 32), padding: '32px', radius: '10px' })
  })

  for (const state of ['device-entry-invalid', 'device-entry-blank']) {
    test(`CLI-TYPE-03: ${state} shows the error under the code field at ${width}px`, async ({ page }) => {
      await open(page, state, width)
      const field = page.getByLabel('Code shown in your CLI')
      await expect(field).toHaveAttribute('aria-invalid', 'true')
      await expect(field).toHaveAccessibleDescription('Check the code shown in your CLI and try again.')
      expect(await field.evaluate(node => [getComputedStyle(node).borderTopWidth, getComputedStyle(node).borderTopColor, getComputedStyle(node).paddingLeft]))
        .toEqual(['2px', 'rgb(30, 37, 43)', '11px'])
      const error = page.locator('.field-error')
      const input = (await field.boundingBox())!
      const below = (await error.boundingBox())!
      expect(Math.round(below.y - (input.y + input.height))).toBe(6)
      const icon = (await error.locator('svg').boundingBox())!
      expect([icon.width, icon.height]).toEqual([16, 16])
      expect(await error.locator('svg').getAttribute('aria-hidden')).toBe('true')
      await expect(page.getByRole('alert')).toHaveCount(0)
    })
  }

  test(`CLI-TYPE-04: a code rejected on the confirm screen shows the failure message above the buttons at ${width}px`, async ({ page }) => {
    await open(page, 'device-confirm-rejected', width)
    const alert = page.getByRole('alert')
    await expect(alert).toHaveText('Check the code shown in your CLI and try again.')
    expect(await alert.evaluate(node => {
      const style = getComputedStyle(node)
      return [style.backgroundColor, style.borderTopWidth, style.borderTopColor, style.borderRadius, style.paddingTop, style.paddingLeft]
    })).toEqual(['rgb(244, 245, 246)', '1px', 'rgb(122, 133, 143)', '8px', '14px', '16px'])
    const icon = (await alert.locator('svg').boundingBox())!
    expect([icon.width, icon.height]).toEqual([20, 20])
    const box = (await alert.boundingBox())!
    const cancel = (await page.getByRole('button', { name: 'Cancel', exact: true }).boundingBox())!
    expect(box.y + box.height).toBeLessThanOrEqual(cancel.y)
  })
}
