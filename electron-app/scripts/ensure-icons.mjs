#!/usr/bin/env node

import { execFileSync } from 'child_process'
import { existsSync } from 'fs'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT_DIR = resolve(__dirname, '..', '..')
const RESOURCES_DIR = resolve(ROOT_DIR, 'electron-app', 'resources')
const ICON_PNG = resolve(RESOURCES_DIR, 'icon.png')
const ICON_ICO = resolve(RESOURCES_DIR, 'icon.ico')
const ICON_ICNS = resolve(RESOURCES_DIR, 'icon.icns')
const ICON_SVG = resolve(RESOURCES_DIR, 'icon.svg')

const needsPng = !existsSync(ICON_PNG)
const needsIco = !existsSync(ICON_ICO)
const needsIcns = process.platform === 'darwin' && !existsSync(ICON_ICNS)

if (!needsPng && !needsIco && !needsIcns) {
  process.exit(0)
}

const sourceIcon = existsSync(ICON_PNG) ? ICON_PNG : (existsSync(ICON_SVG) ? ICON_SVG : '')
if (!sourceIcon) {
  console.warn('[icons] skipped: no icon.png or icon.svg source found in electron-app/resources')
  process.exit(0)
}

execFileSync(process.execPath, [resolve(ROOT_DIR, 'scripts', 'build-icons.mjs'), sourceIcon], {
  cwd: ROOT_DIR,
  stdio: 'inherit',
})
