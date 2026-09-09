/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * REST 루트. 버전(`/v1`)은 붙이지 않는다 — client.ts가 붙인다.
   * 인프라가 `/api`를 주입하며(루트 `.env.example`), 미설정 시에도 `/api`다.
   */
  readonly VITE_API_BASE_URL?: string
}
