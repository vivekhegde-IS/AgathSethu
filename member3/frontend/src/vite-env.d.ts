/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_WEBSOCKET_URL: string
  readonly VITE_ENABLE_MOCK_DATA: string
  readonly VITE_LOG_API_CALLS: string
  readonly VITE_APP_NAME: string
  readonly VITE_APP_ENVIRONMENT: string
  readonly VITE_JWT_STORAGE_KEY: string
  readonly VITE_REFRESH_TOKEN_STORAGE_KEY: string
  readonly VITE_MEMBER_1_ENABLED: string
  readonly VITE_MEMBER_2_ENABLED: string
  readonly VITE_MEMBER_3_ENABLED: string
  readonly VITE_MEMBER_1_BASE_URL: string
  readonly VITE_MEMBER_2_BASE_URL: string
  readonly VITE_MEMBER_3_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
