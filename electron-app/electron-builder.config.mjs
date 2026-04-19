const updateUrl = String(process.env.KENDR_UPDATE_URL || '').trim()
const updateChannel = String(process.env.KENDR_UPDATE_CHANNEL || 'latest').trim() || 'latest'

const publish = updateUrl
  ? [
      {
        provider: 'generic',
        url: updateUrl,
        channel: updateChannel,
      },
    ]
  : undefined

export default {
  appId: 'com.kendr.desktop',
  productName: 'Kendr',
  electronUpdaterCompatibility: '>=2.16',
  directories: {
    output: 'dist',
  },
  files: ['out/**/*'],
  extraResources: [
    {
      from: '.bundled-backend/kendr-backend',
      to: 'kendr-backend',
      filter: ['**/*'],
    },
    {
      from: '../',
      to: 'kendr-backend-source',
      filter: [
        'gateway_server.py',
        'app.py',
        'kendr/**/*',
        'tasks/**/*',
        'mcp_servers/**/*',
        'plugin_templates/**/*',
        'project_templates/**/*',
        'pyproject.toml',
        'requirements.txt',
        '!**/__pycache__/**',
        '!**/*.pyc',
        '!**/*.pyo',
        '!**/.venv/**',
        '!**/electron-app/**',
        '!**/node_modules/**',
        '!**/tests/**',
        '!**/docs/**',
        '!**/output/**',
        '!**/logs/**',
        '!**/.git/**',
        '!**/dist/**',
        '!**/build/**',
        '!**/*.egg-info/**',
        '!**/attached_assets/**',
        '!**/openai_flowchart/**',
        '!**/.deps/**',
      ],
    },
  ],
  win: {
    target: [
      {
        target: 'nsis',
        arch: ['x64'],
      },
    ],
    icon: 'resources/icon.ico',
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: 'Kendr',
  },
  mac: {
    target: [
      {
        target: 'dmg',
        arch: ['x64', 'arm64'],
      },
      {
        target: 'zip',
        arch: ['x64', 'arm64'],
      },
    ],
    icon: 'resources/icon.icns',
    category: 'public.app-category.developer-tools',
    hardenedRuntime: true,
    gatekeeperAssess: false,
  },
  dmg: {
    contents: [
      {
        x: 130,
        y: 220,
      },
      {
        x: 410,
        y: 220,
        type: 'link',
        path: '/Applications',
      },
    ],
  },
  linux: {
    target: [
      {
        target: 'AppImage',
        arch: ['x64'],
      },
      {
        target: 'deb',
        arch: ['x64'],
      },
    ],
    icon: 'resources/icon.png',
    category: 'Development',
  },
  ...(publish ? { publish } : {}),
}
