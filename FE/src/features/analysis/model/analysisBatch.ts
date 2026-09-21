import type {
  AnalysisBatchAccepted,
  AnalysisRequestOutcome,
  AnalysisTarget,
  LatestBatch,
  LatestBatchItem,
  LatestBatchView,
} from '@/features/analysis/api/types'

/**
 * 분석 묶음의 해석 · 티켓 S15P21E102-136.
 *
 * ## 왜 순수 함수로 빼나
 *
 * 이 저장소의 FE 테스트는 jsdom 없이 `node:test`로만 돈다. 컴포넌트 안에 판단이
 * 남으면 검증할 방법이 없고, 이 화면의 판단은 사용자가 새 분석을 시작할 수 있는지를
 * 정하므로 틀리면 조용히 막히거나 조용히 뚫린다.
 *
 * ## 진행률은 세되 퍼센트는 만들지 않는다
 *
 * {@link analysisProgress}가 단계에 대해 세운 규칙을 묶음에도 그대로 둔다. 서버가
 * 아는 것은 "저장소 넷 중 둘이 끝났다" 하나뿐이고, 남은 둘이 얼마나 걸릴지는 저장소
 * 마다 다르다. `2/4`는 사실이고 `50%`는 그 사실을 시간처럼 보이게 만든 값이다.
 */

export type BatchPhase = 'NONE' | 'IN_PROGRESS' | 'COMPLETE'

/**
 * 묶음이 어느 국면인가.
 *
 * `pollAfterSeconds`로 판정하지 않고 개수로 판정한다. 폴링 여부는 서버가 정하는
 * 별개의 값이고, 둘을 겹치면 서버가 폴링을 멈춘 순간 화면이 "완료"라고 말해 버린다 --
 * 실제로는 끝나지 않았는데 폴링만 멎은 경우에도 그렇게 된다.
 */
export function batchPhase(batch: LatestBatch | null | undefined): BatchPhase {
  if (batch == null || batch.totalCount === 0) {
    return 'NONE'
  }
  return batch.completedCount >= batch.totalCount ? 'COMPLETE' : 'IN_PROGRESS'
}

/** 좁은 자리에 쓰는 한 줄. 분모를 반드시 함께 말한다. */
export function batchProgressLabel(batch: LatestBatch | null | undefined): string | null {
  if (batch == null || batch.totalCount === 0) {
    return null
  }
  return `${batch.completedCount}/${batch.totalCount} 완료`
}

/**
 * 저장소마다 칸 하나. `SegmentBar`가 그대로 받는다.
 *
 * 실패를 `NONE`이 아니라 `WEAK`으로 두는 것은, 아직 시작하지 않은 칸과 실패한 칸이
 * 같은 색이면 "무슨 일이 있었는지"를 화면에서 읽을 수 없기 때문이다.
 */
export function batchMarks(
  batch: LatestBatch | null | undefined,
): ('HAVE' | 'WEAK' | 'NONE')[] {
  if (batch == null) {
    return []
  }
  return batch.items.map((item) => {
    if (item.analysisStatus === 'FAILED') {
      return 'WEAK'
    }
    return item.analysisStatus === 'SUCCEEDED' || item.analysisStatus === 'PARTIAL_SUCCEEDED'
      ? 'HAVE'
      : 'NONE'
  })
}

/**
 * 다음 폴링까지 몇 밀리초인가. 멈춰야 하면 `false`.
 *
 * 서버가 준 `pollAfterSeconds`가 유일한 기준이다. 화면이 상태를 보고 따로 판정하면
 * 워커가 느려졌을 때 같이 조정할 방법이 없고, 종료 판정이 두 곳에서 갈린다.
 */
export function batchPollInterval(view: LatestBatchView | undefined): number | false {
  const seconds = view?.batch?.pollAfterSeconds
  return seconds === null || seconds === undefined ? false : seconds * 1000
}

/**
 * 완료 안내와 "새로운 분석 요청하기" 버튼을 보여 줄 때.
 *
 * 닫힘 상태를 boolean이 아니라 **batchId**로 기억한다. boolean이면 새 묶음이
 * 시작되는 순간 낡은 값이 되어, 방금 등록한 분석의 완료 안내가 뜨지 않는다.
 * ID로 두면 다른 묶음이 오는 순간 저절로 다시 열린다.
 */
export function showResetPrompt(
  batch: LatestBatch | null | undefined,
  dismissedBatchId: string | null,
): boolean {
  if (batch == null) {
    return false
  }
  return batchPhase(batch) === 'COMPLETE' && batch.batchId !== dismissedBatchId
}

/** 저장소 이름으로 구성원을 찾는 표. 카드마다 자기 상태를 집어 간다. */
export function itemByRepository(
  batch: LatestBatch | null | undefined,
): Map<string, LatestBatchItem> {
  const table = new Map<string, LatestBatchItem>()
  if (batch == null) {
    return table
  }
  for (const item of batch.items) {
    if (item.repositoryFullName !== null) {
      table.set(item.repositoryFullName, item)
    }
  }
  return table
}

/**
 * 제출을 막아야 하면 그 이유, 아니면 `null`.
 *
 * 화면이 문구를 지어내지 않게 판정과 문구를 같이 둔다. 막힌 이유를 말하지 않고
 * 버튼만 비활성으로 두면 사용자는 무엇이 잘못됐는지 알 수 없다.
 */
export function submitBlockedReason(view: LatestBatchView | undefined): string | null {
  if (view === undefined || view.canSubmit) {
    return null
  }
  return '진행 중인 분석이 끝나면 새로 요청할 수 있어요.'
}

/**
 * 한 번에 고를 수 있는 저장소 수.
 *
 * 서버가 알려 주기 전에는 막지 않는다. 화면이 임의의 숫자를 들고 있으면 서버가 상한을
 * 바꾼 날 둘이 어긋나고, 그때 사용자는 고를 수 있는 것을 못 고르거나 고를 수 없는 것을
 * 고른 뒤에야 거절당한다.
 */
export function selectionLimit(view: LatestBatchView | undefined): number | null {
  const limit = view?.maxBatchSize
  return typeof limit === 'number' && limit > 0 ? limit : null
}

/** 더 고를 수 있는지. 상한을 모르면 막지 않는다. */
export function canSelectMore(
  selectedCount: number,
  view: LatestBatchView | undefined,
): boolean {
  const limit = selectionLimit(view)
  return limit === null || selectedCount < limit
}

/**
 * 상한에 닿았을 때의 한 줄. 닿지 않았으면 `null`.
 *
 * 체크박스만 비활성으로 두면 사용자는 자기 화면이 고장 난 줄 안다.
 */
export function selectionLimitNotice(
  selectedCount: number,
  view: LatestBatchView | undefined,
): string | null {
  const limit = selectionLimit(view)
  if (limit === null || selectedCount < limit) {
    return null
  }
  return `한 번에 ${limit}개까지 요청할 수 있어요. 더 고르려면 먼저 몇 개를 빼 주세요.`
}

/**
 * 제출 자체가 거절됐을 때 보여 줄 문장.
 *
 * 항목별 실패는 응답 본문으로 오지만, 요청 전체가 거절되면 예외로만 온다. 그 경로에
 * 표시가 없으면 사용자는 버튼을 눌러도 아무 일도 일어나지 않는 화면을 본다 -- 상한
 * 초과(`AN-400-1`)가 정확히 그랬다.
 *
 * `ApiError`가 아닌 것(네트워크 끊김 등)도 말없이 넘기지 않는다.
 *
 * ## `instanceof`를 쓰지 않는 이유
 *
 * 이 파일은 순수 모델이고 테스트는 `node:test`가 직접 돌린다. 그 실행기는 `@/` 별칭을
 * 풀지 못하므로, 여기서 `ApiError`를 런타임 import하면 이 모듈 전체가 테스트에서
 * 불러와지지 않는다. 클래스가 아니라 모양으로 판정한다 -- 필요한 것은 코드와 문장
 * 두 개뿐이다.
 */
export function submitFailureMessage(error: unknown): string | null {
  if (error === null || error === undefined) {
    return null
  }
  if (isApiFailure(error)) {
    return `${error.message} (코드 ${error.code})`
  }
  return '요청을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

function isApiFailure(error: unknown): error is { code: string; message: string } {
  if (typeof error !== 'object' || error === null) {
    return false
  }
  const candidate = error as { code?: unknown; message?: unknown }
  return typeof candidate.code === 'string' && typeof candidate.message === 'string'
}

/**
 * 배치 응답을 저장소별 결과로 편다.
 *
 * 키는 **보낸 이름**이다. 서버가 GitHub 정규 표기로 바꾼 이름으로 키잉하면, 대소문자가
 * 다르게 입력된 저장소의 결과가 어느 카드에도 붙지 않는다.
 */
export function outcomesFromBatchResponse(
  response: AnalysisBatchAccepted,
  branchByRepo: ReadonlyMap<string, string>,
): Map<string, AnalysisRequestOutcome> {
  const outcomes = new Map<string, AnalysisRequestOutcome>()
  for (const item of response.items) {
    const target: AnalysisTarget = {
      repositoryFullName: item.requestedRepositoryFullName,
      branchName:
        item.branchName ?? branchByRepo.get(item.requestedRepositoryFullName) ?? '',
    }
    if (item.outcome === 'FAILED' || item.analysisId === null) {
      outcomes.set(item.requestedRepositoryFullName, {
        target,
        ok: false,
        error: {
          code: item.errorCode,
          message: item.message ?? '요청을 처리할 수 없습니다.',
        },
      })
      continue
    }
    outcomes.set(item.requestedRepositoryFullName, {
      target,
      ok: true,
      reused: item.outcome === 'REUSED',
      accepted: {
        analysisId: item.analysisId,
        status: item.status ?? 'QUEUED',
        repositoryFullName:
          item.repositoryFullName ?? item.requestedRepositoryFullName,
        branchName: target.branchName,
        commitSha: item.commitSha ?? '',
        statusUrl: item.statusUrl ?? `/api/v1/analyses/${item.analysisId}`,
      },
    })
  }
  return outcomes
}
