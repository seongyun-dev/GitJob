/**
 * 수요 조회 경로 · 티켓 S15P21E102-339.
 *
 * BE는 `targetRole`의 **유무**로 모집단을 고른다 — 있으면 그 직무의 활성 수요, 없으면
 * 지금 확보한 공고 전체의 시장 수요다. 그래서 직무가 없을 때는 빈 값을 실어 보내는 것이
 * 아니라 파라미터 자체가 없어야 한다. `targetRole=`이나 `targetRole=undefined`는
 * "고르지 않았다"가 아니라 그런 이름의 직무를 달라는 요청이고, C가 422를 준다.
 *
 * `matchingApi`가 아니라 여기 있는 이유는 이 규칙을 네트워크 없이 검증하기 위해서다 —
 * `npm test`는 Vite 없이 node로 돌아 `@/` alias가 있는 모듈을 불러오지 못한다.
 */
export function jobDemandsPath(params: {
  targetRole?: string
  regions: readonly string[]
  careerLevels: readonly string[]
}): string {
  const query = new URLSearchParams()
  if (params.targetRole !== undefined && params.targetRole !== '') {
    query.set('targetRole', params.targetRole)
  }
  params.regions.forEach((region) => query.append('regions', region))
  params.careerLevels.forEach((level) => query.append('careerLevels', level))
  const search = query.toString()
  return search === '' ? '/job-demands' : `/job-demands?${search}`
}
