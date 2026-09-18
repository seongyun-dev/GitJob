import type { StateKind } from '@/shared/ui/StateCard'

/**
 * 분석 진행 상태의 해석 · 티켓 S15P21E102-326.
 *
 * ## 왜 따로 두나
 *
 * 분석 상태를 읽는 자리가 둘이다 — 저장소 선택 화면의 패널(주 흐름)과
 * `/analyses/:analysisId`(주소로 직접 들어왔을 때). 두 곳이 같은 상태를 다르게
 * 말하면 같은 분석이 화면마다 다른 일을 하는 것처럼 보인다. 판정과 문구를 한곳에
 * 두고 양쪽이 가져다 쓴다.
 *
 * ## 무엇을 고쳤나
 *
 * 이전 화면은 `FAILED`·`SUCCEEDED`·`PARTIAL_SUCCEEDED`만 분기하고 나머지를 하나의
 * fallback으로 묶어 **"분석하고 있어요"** 라고 단언했다. 그 fallback에는 `QUEUED`가
 * 들어간다 — 워커가 아직 집어가지 않아 `started_at`이 NULL인, 시작조차 되지 않은
 * 상태다. 워커가 내려가 있으면 화면은 몇 분이든 진행 중이라고 말한다.
 *
 * 이 제품에서 이것은 "판정하지 않음"과 "충족하지 못함"을 합치는 것과 같은 종류의
 * 잘못이다. 대기와 진행은 서로 다른 사실이다.
 *
 * ## 진행률을 만들지 않는다
 *
 * 서버가 주는 `progressPercent`는 0 또는 100뿐이고 `AnalysisJob`의 stage 상수도
 * `WAITING_FOR_WORKER`·`COMPLETED`·`FAILED` 세 개뿐이다 — 중간이 없다. BE의
 * `AnalysisStatusResponse` 주석이 "워커가 중간 진행을 발행하지 않아 그 사이 값을
 * 만들 근거가 없다"고 적어 두었다. 그래서 여기서도 퍼센트·남은 시간·단계별 진척을
 * 계산하지 않는다. 워커가 중간 진행을 발행하기 시작하면 그때 이 모듈이 받는다.
 */

/**
 * 화면이 구분하는 다섯 국면.
 *
 * 서버 `analysisStatus`와 이름이 겹치지만 같은 것이 아니다. 서버는 저장 값을 응답
 * 경계에서 다섯 값으로 접어 주고, 이쪽은 **화면이 다르게 그려야 하는 단위**다.
 * 지금은 1:1이지만 서버가 값을 늘려도 화면 분기가 따라 늘어나지 않게 한 겹 둔다.
 */
export type AnalysisPhase = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED'

/**
 * 서버 상태 문자열을 국면으로 옮긴다.
 *
 * 모르는 값은 `FAILED`로 접는다. BE가 이미 응답 경계에서 다섯 값으로 좁히므로
 * 여기 도달하는 미지의 값은 계약이 어긋났다는 뜻이고, 그때 화면이 "진행 중"으로
 * 남아 무한 폴링에 갇히는 것이 가장 나쁜 결과다.
 */
export function analysisPhase(analysisStatus: string): AnalysisPhase {
  switch (analysisStatus) {
    case 'QUEUED':
      return 'QUEUED'
    case 'RUNNING':
      return 'RUNNING'
    case 'SUCCEEDED':
      return 'SUCCEEDED'
    case 'PARTIAL_SUCCEEDED':
      return 'PARTIAL'
    default:
      return 'FAILED'
  }
}

/** 결과를 보러 갈 수 있는 국면인지. 성공과 부분 성공 모두 확인할 근거가 남는다. */
export function hasResult(phase: AnalysisPhase): boolean {
  return phase === 'SUCCEEDED' || phase === 'PARTIAL'
}

/** 아직 끝나지 않은 국면인지. 폴링과 로딩 표시를 이 값으로 정한다. */
export function isPending(phase: AnalysisPhase): boolean {
  return phase === 'QUEUED' || phase === 'RUNNING'
}

export interface PhaseCopy {
  kind: StateKind
  title: string
  description: string
}

/**
 * 국면별 문구.
 *
 * `QUEUED`는 시작되지 않았다고 **분명히 말한다.** "곧 시작됩니다" 같은 약속을 하지
 * 않는 것은 언제 시작될지 우리가 모르기 때문이다 — 큐 길이도 워커 생존 여부도
 * 화면에 오지 않는다.
 */
export function phaseCopy(phase: AnalysisPhase): PhaseCopy {
  switch (phase) {
    case 'QUEUED':
      return {
        kind: 'PREPARING',
        title: '분석 차례를 기다리고 있어요',
        description: '요청이 접수됐고 아직 시작되지 않았습니다. 차례가 되면 자동으로 시작됩니다.',
      }
    case 'RUNNING':
      return {
        kind: 'LOADING',
        title: '분석하고 있어요',
        description: '이 화면을 벗어나도 분석은 계속됩니다.',
      }
    case 'SUCCEEDED':
      return {
        kind: 'SUCCESS',
        title: '분석이 끝났어요',
        description: '확인된 기술과 판정 근거를 볼 수 있습니다.',
      }
    case 'PARTIAL':
      return {
        kind: 'PARTIAL',
        title: '일부만 확인했어요',
        description: '확인된 기술과 판정 근거를 볼 수 있습니다.',
      }
    case 'FAILED':
      return {
        kind: 'ERROR',
        title: '분석을 마치지 못했어요',
        description: '아래 사유를 확인하고 다시 시도해 주세요.',
      }
  }
}

/** hero 제목. 페이지 상단은 카드보다 짧게 끊는다. */
export function phaseHeadline(phase: AnalysisPhase): string {
  switch (phase) {
    case 'QUEUED':
      return '분석 차례를 기다리고 있어요'
    case 'RUNNING':
      return 'GitHub를 분석하고 있어요'
    case 'SUCCEEDED':
    case 'PARTIAL':
      return '분석이 끝났어요'
    case 'FAILED':
      return '분석을 마치지 못했어요'
  }
}

/**
 * 실패 사유의 종류.
 *
 * `errorCode`는 BE가 주는 값이고 화면은 이 중 몇 가지에만 다른 복구 경로를 준다.
 * 안내 문구는 여기 두고, 이동 링크(JSX)는 화면마다 자리가 달라 호출부가 만든다.
 */
export type FailureKind = 'GITHUB_RECONNECT' | 'REPOSITORY' | 'CREDENTIAL_BROKER' | 'GENERIC'

export function failureKind(errorCode: string | null): FailureKind {
  if (errorCode === 'GITHUB_RECONNECT_REQUIRED') {
    return 'GITHUB_RECONNECT'
  }
  if (errorCode === 'REPOSITORY_NOT_ACCESSIBLE' || errorCode === 'REPOSITORY_CREDENTIAL_NOT_FOUND') {
    return 'REPOSITORY'
  }
  if (
    errorCode === 'CREDENTIAL_BROKER_UNAVAILABLE' ||
    errorCode === 'CREDENTIAL_BROKER_INVALID_RESPONSE' ||
    errorCode === 'CREDENTIAL_BROKER_UNAUTHORIZED'
  ) {
    return 'CREDENTIAL_BROKER'
  }
  return 'GENERIC'
}

export function failureCopy(kind: FailureKind): { title: string; description: string } {
  switch (kind) {
    case 'GITHUB_RECONNECT':
      return {
        title: 'GitHub 연결을 갱신해 주세요',
        description: '비공개 저장소 권한이 만료되었거나 조직 승인이 필요합니다.',
      }
    case 'REPOSITORY':
      return {
        title: '저장소에 접근할 수 없어요',
        description: '저장소가 삭제되었거나 현재 GitHub 계정의 접근 권한이 바뀌었습니다.',
      }
    case 'CREDENTIAL_BROKER':
      return {
        title: '비공개 저장소 연결이 지연되고 있어요',
        description: '서비스 연결을 복구한 뒤 다시 분석해 주세요.',
      }
    case 'GENERIC':
      return {
        title: '분석에 실패했어요',
        description: '아래 사유를 확인하고 다시 시도해 주세요.',
      }
  }
}

/**
 * 요청 후 얼마나 지났는지. 분 단위로만 센다.
 *
 * 초를 세지 않는 이유는 두 가지다. 상태 폴링이 서버가 정한 간격(지금 5초)으로만
 * 돌아 그 사이 값은 어차피 화면에 반영되지 않고, 초 단위 카운터는 진행되고 있다는
 * 인상을 주는데 대기 중에는 아무 일도 일어나지 않기 때문이다.
 *
 * 1분 미만이면 `null`이다 — 갓 누른 버튼 옆에 "0분 경과"를 붙일 이유가 없다.
 * 파싱에 실패해도 `null`이다. 시각을 지어내지 않는다.
 */
export function waitedMinutes(requestedAt: string, now: number = Date.now()): number | null {
  const parsed = Date.parse(requestedAt)
  if (Number.isNaN(parsed)) {
    return null
  }
  const minutes = Math.floor((now - parsed) / 60_000)
  return minutes >= 1 ? minutes : null
}
