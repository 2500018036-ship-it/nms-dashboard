import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'template-dashboard/**']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  { files: ['vite.config.js', 'config/**/*.js', 'tests/**/*.js'], languageOptions: { globals: globals.node } },
  // These existing public helpers are shared by several template components.
  { files: ['src/components/ui.jsx', 'src/devices/InventoryModals.jsx'], rules: {
    'react-refresh/only-export-components': ['error', { allowExportNames: ['formatTime', 'percentage', 'downloadJson'] }],
  } },
])
