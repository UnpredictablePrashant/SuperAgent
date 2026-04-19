import { spawn } from 'child_process'

const updateUrl = String(process.env.KENDR_UPDATE_URL || '').trim()
if (!updateUrl) {
  console.error('KENDR_UPDATE_URL is required for npm run release.')
  process.exit(1)
}

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm'
const builderCmd = process.platform === 'win32'
  ? 'node_modules/.bin/electron-builder.cmd'
  : 'node_modules/.bin/electron-builder'

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      shell: false,
      env: process.env,
    })
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${command} exited with code ${code}`))
    })
  })
}

try {
  await run(npmCmd, ['run', 'build:release-assets'])
  await run(npmCmd, ['run', 'build'])
  await run(builderCmd, ['-c', './electron-builder.config.mjs', '--publish', 'always'])
} catch (error) {
  console.error(error.message || String(error))
  process.exit(1)
}
