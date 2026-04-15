#!/usr/bin/env node

import { execFileSync } from 'child_process'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT_DIR = resolve(__dirname, '..', '..')
const BUILD_SCRIPT = resolve(ROOT_DIR, 'scripts', 'build_backend_bundle.py')
const OUTPUT_DIR = resolve(ROOT_DIR, 'electron-app', '.bundled-backend')

function runVersionCheck(cmd, args = ['--version']) {
  try {
    execFileSync(cmd, args, { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

function findPython() {
  const configured = process.env.PYTHON?.trim()
  const candidates = [
    configured ? { cmd: configured, args: [] } : null,
    process.platform === 'win32' ? { cmd: 'py', args: ['-3'] } : null,
    { cmd: 'python3', args: [] },
    { cmd: 'python', args: [] },
  ].filter(Boolean)

  for (const candidate of candidates) {
    const versionArgs = [...candidate.args, '--version']
    if (runVersionCheck(candidate.cmd, versionArgs)) {
      return candidate
    }
  }
  throw new Error(
    'Python 3.10+ is required to build the desktop backend bundle. ' +
    'Set PYTHON=/path/to/python if it is not on PATH.'
  )
}

const python = findPython()
const args = [
  ...python.args,
  BUILD_SCRIPT,
  '--output-dir',
  OUTPUT_DIR,
]

execFileSync(python.cmd, args, {
  cwd: ROOT_DIR,
  stdio: 'inherit',
})
