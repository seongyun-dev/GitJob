import {
  parseTechnologyEvidence,
  parseTechnologyProfile,
} from '@/features/evidence/api/parseEvidence'
import type {
  TechnologyEvidence,
  TechnologyEvidenceParams,
  TechnologyProfile,
  TechnologyProfileParams,
} from '@/features/evidence/api/types'
import { get } from '@/shared/api/client'

/**
 * Evidence 조회 HTTP 계층 · 티켓 S15P21E102-208.
 *
 * 이 파일만 경로 문자열을 안다. 봉투 해제·오류 변환은 `shared/api/client`가 하고,
 * `data` 안쪽 검증은 `parseEvidence`가 한다. 버전 접두(`/v1`)는 client가 붙이므로
 * 여기서 쓰지 않는다. `features/analysis/api/repositoriesApi.ts`와 같은 구조다.
 *
 * **두 엔드포인트 모두 BE에 아직 없다**(명세 상태 `시작 전`). 경로·파라미터는 B조 API
 * 명세서 v0.1의 B-FN-010·B-FN-011이고, 호출하면 `HTTP-404`가 온다(계약 1-3의 FE 합성
 * 코드). 화면을 이 함수에 붙이는 것은 137·138의 일이며, 이 티켓은 붙일 자리를
 * 명세대로 만들어 두는 데까지다.
 *
 * `get<unknown>`으로 받는 이유는 제네릭으로 타입을 주장하면 검증 없이 그 타입이라고
 * 믿게 되기 때문이다. 실제 타입은 파서를 통과한 뒤에만 생긴다.
 */

/**
 * 빈 값을 뺀 쿼리 문자열을 만든다.
 *
 * 명세의 파라미터가 전부 optional이고 기본값을 **서버가** 정한다(`scopeType` 기본
 * `ALL`, `includeExcluded` 기본 false). FE가 기본값을 만들어 보내면 서버 기본값이
 * 바뀔 때 두 곳이 어긋나므로, 지정하지 않은 값은 보내지 않는다.
 */
function toQuery(params: Record<string, string | boolean | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      query.set(key, String(value))
    }
  }
  const serialized = query.toString()
  return serialized === '' ? '' : `?${serialized}`
}

/**
 * 기술 프로필 · 명세 B-FN-010 (화면 S6).
 *
 * 경로에 사용자 식별자가 없다 — 세션 쿠키로 who를 정한다(client의 `credentials`).
 *
 * `analysisId`를 생략하면 **가장 최근 종료 분석**이 기준이다. 설계 4-1의 캐시 키가
 * 증거 계열을 `['analysis', analysisId, ...]`로 묶고 `staleTime: Infinity`를 주는
 * 근거("analysisId가 같으면 응답이 불변")는 이 파라미터를 실제로 넘길 때만 성립한다.
 * 생략하면 같은 키에 다른 분석 결과가 담길 수 있으므로, 호출부는 분석을 특정할 수
 * 있게 되면 값을 넘긴다.
 */
export async function fetchTechnologyProfile(
  params: TechnologyProfileParams = {},
): Promise<TechnologyProfile> {
  const path = `/me/profile${toQuery({ analysisId: params.analysisId })}`
  return parseTechnologyProfile(await get<unknown>(path))
}

/**
 * 기술 Evidence 근거 · 명세 B-FN-011 (화면 S7).
 *
 * `techId`는 Registry의 표준 `tech_id`(소문자 kebab-case)라 그대로 경로에 넣어도
 * 문제가 없지만 인코딩한다. 이 값은 라우트 파라미터에서 오므로 주소창에서 고칠 수
 * 있고, `../`나 `?`가 섞이면 다른 엔드포인트를 부르게 된다.
 */
export async function fetchTechnologyEvidence(
  techId: string,
  params: TechnologyEvidenceParams = {},
): Promise<TechnologyEvidence> {
  const query = toQuery({
    analysisId: params.analysisId,
    scopeType: params.scopeType,
    repoFullName: params.repoFullName,
    includeExcluded: params.includeExcluded,
  })
  const path = `/me/technologies/${encodeURIComponent(techId)}/evidence${query}`
  return parseTechnologyEvidence(await get<unknown>(path))
}
