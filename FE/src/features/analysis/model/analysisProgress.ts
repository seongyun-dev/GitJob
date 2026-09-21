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
 * ## 단계는 받고, 진행률은 여전히 만들지 않는다
 *
 * 워커가 이제 단계 전환을 발행한다 — 저장소 분석을 시작할 때와 기여도 판정을
 * 시작할 때. 그 값이 `currentStage`로 내려오므로 {@link analysisSteps}가 어느 칸에
 * 불을 켤지 안다.
 *
 * 그래도 퍼센트와 남은 시간은 만들지 않는다. 알게 된 것은 "지금 어느 단계인가"
 * 하나뿐이고, 한 단계가 얼마나 걸릴지는 저장소마다 다르며 서버도 알려 주지 않는다.
 * `progressPercent`는 여전히 0 또는 100만 온다. 단계 수로 막대를 채우면 그것은
 * 진척이 아니라 단계의 개수를 그린 것이고, 시간으로 채우면 이 화면이 처음부터
 * 거절해 온 지어낸 값이 된다.
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

export type AnalysisStepState = 'WAITING' | 'RUNNING' | 'DONE'

export interface AnalysisStepView {
  name: string
  detail: string
  state: AnalysisStepState
}

/**
 * 화면이 그리는 단계와, 그 단계를 알려 주는 서버 `currentStage`.
 *
 * ## 왜 셋뿐인가
 *
 * 워커가 실제로 알리는 전환이 둘이기 때문이다 — 클론을 마치고 판정을 시작할 때와,
 * git blame 으로 기여자를 가리기 시작할 때. 세 번째는 일이 아니라 끝났다는 표시다.
 *
 * 디자인 `Final v2`의 네 칸(저장소 확인 · 파일 구조 분석 · Evidence 판정 · 사용자
 * 기여 확인)을 그대로 두지 않은 것은, 가운데 두 칸을 채울 값이 서버에 없기 때문이다.
 * 워커는 그 셋을 한 구간으로 돌고 중간에 아무것도 발행하지 않는다. 네 칸을 유지하면
 * 남은 두 칸은 시간으로 칠하는 수밖에 없고, 그것은 이 화면이 진행률·남은 시간과
 * 함께 이미 거절한 종류의 값이다.
 */
const STEPS = [
  {
    stage: 'ANALYZING_REPOSITORY',
    name: '저장소 분석',
    detail: '의존성 선언과 소스 트리를 읽어 기술 사용 근거를 찾습니다',
  },
  {
    stage: 'ATTRIBUTING_CONTRIBUTION',
    name: '개인 기여도 판정',
    detail: '커밋 작성자를 대조해 본인이 쓴 근거를 가립니다',
  },
  {
    stage: 'COMPLETED',
    name: '완료',
    detail: '확인된 기술과 근거를 볼 수 있습니다',
  },
] as const

/**
 * 국면과 `currentStage`로 단계별 표시를 만든다.
 *
 * ## 끝난 분석은 전부 완료로 그린다
 *
 * 기여도 판정을 끄고 돌리는 배포가 있고(`ANALYSIS_ATTRIBUTE_AUTHORS`), 그때는 두
 * 번째 전환이 아예 발행되지 않는다. 폴링이 5초마다 물으므로 켜져 있는 배포에서도
 * 그 단계를 지나치는 순간을 놓칠 수 있다. 화면은 이 둘을 구분할 수 없다 — 성공한
 * 분석에서 한 칸만 비워 두면, 무엇이 빠졌는지 알 수 없는 채로 남는다.
 *
 * ## 실패하면 어디까지 갔는지 말하지 않는다
 *
 * BE 가 실패 시 `current_stage` 를 `FAILED` 로 덮어써서 도달한 단계가 남지 않는다.
 * 화면이 마지막으로 본 단계를 기억해 둘 수도 있지만 새로고침하면 사라지는 기억이고,
 * 그러면 같은 분석이 탭마다 다른 곳에서 멈춘 것처럼 보인다. 실패의 내용은 사유
 * 카드가 말한다.
 */
export function analysisSteps(
  phase: AnalysisPhase,
  currentStage: string | undefined,
): AnalysisStepView[] {
  const reached = STEPS.findIndex((step) => step.stage === currentStage)

  return STEPS.map((step, index) => ({
    name: step.name,
    detail: step.detail,
    state: stepState(phase, index, reached),
  }))
}

function stepState(phase: AnalysisPhase, index: number, reached: number): AnalysisStepState {
  if (hasResult(phase)) {
    return 'DONE'
  }
  if (phase === 'QUEUED' || phase === 'FAILED') {
    return 'WAITING'
  }
  /*
   * 진행 중인데 모르는 단계면 첫 칸을 진행으로 둔다. 워커가 이 화면보다 새 단계를
   * 쓰기 시작했다는 뜻이고, 그때 아무 칸도 켜지 않으면 화면은 멈춰 보인다.
   */
  const current = reached < 0 ? 0 : reached
  if (index < current) {
    return 'DONE'
  }
  return index === current ? 'RUNNING' : 'WAITING'
}

/**
 * 좁은 자리에 쓰는 한 줄. 저장소 선택 화면의 패널(372px)은 칸 셋을 펼 폭이 없다.
 *
 * 진행 중이 아닐 때 `null` 인 것은, 대기·완료·실패의 문구를 이미 국면 쪽
 * ({@link phaseCopy})이 말하고 있어 같은 자리에 두 번 적을 이유가 없기 때문이다.
 */
export function currentStepLabel(
  phase: AnalysisPhase,
  currentStage: string | undefined,
): string | null {
  if (phase !== 'RUNNING') {
    return null
  }
  const steps = analysisSteps(phase, currentStage)
  const index = steps.findIndex((step) => step.state === 'RUNNING')
  const running = steps[index]
  if (running === undefined) {
    return null
  }
  return `${index + 1}/${steps.length} · ${running.name}`
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
export type FailureKind =
  | 'GITHUB_RECONNECT'
  | 'REPOSITORY'
  | 'CREDENTIAL_BROKER'
  | 'TIMED_OUT'
  | 'GENERIC'

export function failureKind(errorCode: string | null): FailureKind {
  if (errorCode === 'GITHUB_RECONNECT_REQUIRED') {
    return 'GITHUB_RECONNECT'
  }
  /*
   * 서버가 응답 없는 분석을 정리하며 붙인 코드다. 사용자가 뭘 잘못한 것이 아니라
   * 워커가 집어 가지 못했다는 뜻이라, GENERIC 의 "분석에 실패했어요"로 접으면
   * 자기 저장소에 문제가 있는 줄 읽는다.
   */
  if (errorCode === 'ANALYSIS_TIMED_OUT') {
    return 'TIMED_OUT'
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
    case 'TIMED_OUT':
      return {
        title: '응답이 없어 중단했어요',
        description: '서버가 분석을 시작하지 못했습니다. 다시 요청해 주세요.',
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
