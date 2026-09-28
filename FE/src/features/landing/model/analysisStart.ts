import type { Me } from '@/features/auth/api/me'

export type AnalysisStartMode =
  | 'CHECKING'
  | 'GITHUB_LOGIN'
  | 'GITHUB_CONNECT'
  | 'REPOSITORY_SELECTION'

/** HttpOnly 세션의 조회 결과를 랜딩 CTA의 단 하나의 이동 규칙으로 바꾼다. */
export function analysisStartMode(me: Me | null | undefined): AnalysisStartMode {
  if (me === undefined) {
    return 'CHECKING'
  }
  if (me === null) {
    return 'GITHUB_LOGIN'
  }
  return me.githubConnected ? 'REPOSITORY_SELECTION' : 'GITHUB_CONNECT'
}
