/**
 * 마이페이지 왼쪽 두 카드가 쓰는 표시 규칙 · 티켓 S15P21E102-318.
 *
 * <h2>왜 밖에 두나</h2>
 *
 * 이 카드들이 하는 말은 "무엇이 설정돼 있는가"다. 값이 없을 때 무엇이라고 쓰는지가
 * 곧 화면이 주장하는 사실이라, 화면을 띄우지 않고 표로 확인할 수 있어야 한다. 이전 판이
 * 정확히 그 자리에서 틀렸다 — 조회가 없는 값을 `PREPARING`으로 그려, GitHub으로 정상
 * 로그인한 사람이 자기 계정 화면에서 "계정 정보를 아직 불러올 수 없어요"를 봤다.
 *
 * 아무것도 import 하지 않는다. `@/` 별칭은 Vite 가 푸는 것이라 별칭을 쓰면
 * `node --test` 에서 해석되지 않는다. 직무 라벨은 부르는 쪽이
 * `matching/model/targetOptions` 로 풀어서 넘기고, 저장소 수도 이미 조회된 값이 들어온다.
 */

/** 값이 없거나 아직 모를 때 쓰는 한 문장. 두 행이 같은 말을 쓰게 한곳에 둔다. */
const NOT_SELECTED = '아직 선택하지 않음'

/**
 * 카드에 크게 적는 이름.
 *
 * BE 는 프로필 이름이 없으면 GitHub 핸들로 접어서 주므로(`MeResponse` 주석) 보통은 값이
 * 있다. 그래도 공백만 남는 경우까지 막아 둔다 — 이름 자리가 비면 아바타만 떠 있는
 * 모양이 된다. `UserMenu` 와 같은 규칙이다.
 */
export function accountName(displayName: string): string {
  const trimmed = displayName.trim()
  return trimmed === '' ? '사용자' : trimmed
}

export interface AnalysisSettingsInput {
  /** 이미 사람이 읽는 이름으로 바뀐 직무. 고르지 않았으면 `null`. */
  targetRoleLabel: string | null
  /**
   * 분석 결과가 남아 있는 저장소 수 · `GET /me/technologies` 의 `summary.repositoryCount`.
   *
   * **현재 선택 상태가 아니다.** BE 가 `count(DISTINCT l.repository_id) FROM latest` 로
   * 세므로 저장소별 최신 완료 분석 기준이다(`TechnologyProfileStore.summary`). 선택을
   * 바꾸고 아직 분석하지 않았거나, 선택에서 뺐지만 과거 분석이 남아 있으면 지금 고른
   * 목록과 어긋난다.
   *
   * 조회 전·실패면 `null`.
   */
  analyzedRepositoryCount: number | null
}

export interface AnalysisSettingsRows {
  repository: string
  targetRole: string
}

/**
 * 두 설정 행의 문구.
 *
 * 저장소 행이 "분석한"이라고 말하는 것이 핵심이다. 같은 숫자를 "N개 선택됨"으로 적으면
 * 화면이 현재 선택을 주장하게 되는데, 그 값을 주는 조회는 아직 없다
 * (`GET /me/repositories/selection` 은 BE 에 매핑이 없다 · 2026-09-18 확인). Evidence
 * 개요도 같은 값을 `분석한 저장소`로 부른다 — 두 화면이 같은 숫자를 다른 이름으로
 * 부르지 않게 맞춘다.
 *
 * `0` 과 `null` 은 같은 문구로 접는다. 둘 다 "아직 분석 결과가 없다"는 같은 사실이고,
 * 조회 실패와 이력 없음을 사용자가 구분할 이유가 없다.
 */
export function analysisSettingsRows({
  targetRoleLabel,
  analyzedRepositoryCount,
}: AnalysisSettingsInput): AnalysisSettingsRows {
  return {
    repository:
      analyzedRepositoryCount === null || analyzedRepositoryCount === 0
        ? '분석 이력 없음'
        : `분석한 저장소 ${analyzedRepositoryCount}개`,
    targetRole: targetRoleLabel ?? NOT_SELECTED,
  }
}
