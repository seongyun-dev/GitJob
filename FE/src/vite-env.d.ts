/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * REST 루트. 버전(`/v1`)은 붙이지 않는다 — client.ts가 붙인다.
   * 인프라가 `/api`를 주입하며(루트 `.env.example`), 미설정 시에도 `/api`다.
   */
  readonly VITE_API_BASE_URL?: string

  /**
   * 디자인 fixture 스위치. `'on'`일 때만 켜진다(`src/mocks/designFixtures.ts`).
   * 인프라가 주입하는 값이 아니라 로컬 디자인 작업 전용이라 루트 `.env.example`에 없다.
   */
  readonly VITE_DESIGN_FIXTURES?: string
}
