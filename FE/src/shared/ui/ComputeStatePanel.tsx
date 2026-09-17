import { ApiError } from '@/shared/api/client'
import { hasComputedValue } from '@/shared/api/computeState'
import type { ComputeState } from '@/shared/api/computeState'
import type { DataStatus } from '@/shared/types/domain'
import { StateCard } from '@/shared/ui/StateCard'
import type { StateKind } from '@/shared/ui/StateCard'

/**
 * 계산 계열 응답의 상태를 화면으로 (S15P21E102-279).
 *
 * <h2>왜 오류와 상태를 나누는가</h2>
 *
 * BE는 "계산 중"을 200 + `dataStatus=PREPARING`으로 준다. 오류가 아니기 때문이다 --
 * 잠시 뒤 값이 생기고, 사용자가 할 일은 기다리는 것뿐이다. 이것을 오류 화면으로
 * 그리면 사용자는 무언가 잘못됐다고 읽고 재시도를 반복한다.
 *
 * 그래서 이 컴포넌트는 두 축을 다룬다. `ApiError`(4xx·5xx)는 `QueryStatePanel`이
 * 맡고, 여기서는 200 응답 안의 상태만 본다.
 *
 * <h2>값이 없는 것과 상태가 나쁜 것</h2>
 *
 * `PARTIAL`은 값이 <b>있다</b>. 일부 저장소를 못 읽었을 뿐이므로 화면을 덮지 않고
 * 배너로만 알린다. 나머지 상태는 보여 줄 값이 없으므로 카드로 자리를 채운다.
 */

/** 상태별 문구. 사유(`statusReason`)까지 보고 정한다. */
interface Copy {
  kind: StateKind
  title: string
  description: string
}

const COPY: Readonly<Record<string, Copy>> = {
  COMPUTING: {
    kind: 'PREPARING',
    title: '결과를 계산하고 있어요',
    description: '분석한 기술을 공고 요구와 대조하는 중입니다. 잠시 뒤 자동으로 표시됩니다.',
  },
  COHORT_NOT_PREPARED: {
    kind: 'PREPARING',
    title: '비교할 공고를 준비하고 있어요',
    description:
      '선택한 직무·지역·경력 조건의 공고 집합이 아직 준비되지 않았습니다. 준비되면 자동으로 표시됩니다.',
  },
  MATCHING_NOT_PREPARED: {
    kind: 'PREPARING',
    title: '공고 대조 결과를 준비하고 있어요',
    description: '이전 계산에는 공고별 대조가 없습니다. 다음 계산에서 채워집니다.',
  },
  INSUFFICIENT_EVIDENCE: {
    kind: 'EMPTY',
    title: '비교할 기술 정보가 아직 없어요',
    description:
      '저장소를 분석하면 그 결과로 공고 요구 기술과 비교합니다. 분석한 저장소가 없으면 대조할 것이 없습니다.',
  },
  INSUFFICIENT_JOB_SAMPLE: {
    kind: 'INSUFFICIENT_DATA',
    title: '비교할 공고 표본이 부족해요',
    description:
      '조건에 맞는 공고가 판정에 필요한 수에 못 미칩니다. 지역이나 경력 범위를 넓히면 표본이 늘어납니다.',
  },
  NO_CANDIDATES: {
    kind: 'EMPTY',
    title: '추천할 기술이 없어요',
    description: '요구 기술을 이미 충족했거나, 선행 조건이 갖춰진 후보가 없습니다.',
  },
  REANALYSIS_REQUIRED_NO_RULE_PACK: {
    kind: 'ERROR',
    title: '저장소를 다시 분석해야 해요',
    description:
      '이전 분석 결과에 판정 기준 정보가 없어 공고와 대조할 수 없습니다. 기다려도 생기지 않으니 저장소를 다시 분석해 주세요.',
  },
  REANALYSIS_REQUIRED_MIXED_RULE_PACK: {
    kind: 'ERROR',
    title: '저장소마다 판정 기준이 달라요',
    description:
      '저장소들이 서로 다른 기준으로 분석돼 하나로 비교할 수 없습니다. 저장소를 다시 분석하면 같은 기준으로 맞춰집니다.',
  },
  RESULT_TOO_LARGE: {
    kind: 'ERROR',
    title: '결과가 너무 커서 표시할 수 없어요',
    description: '조건을 좁히면 다시 계산할 수 있습니다.',
  },
  JOB_TREND_PERIODS_REQUIRED: {
    kind: 'NO_DATA',
    title: '조회할 공고 기간을 선택해 주세요',
    description: '공고 추세는 월별 기간을 지정해야 같은 기간의 수요를 비교할 수 있습니다.',
  },
  JOB_TREND_TARGET_ROLE_REQUIRED: {
    kind: 'NO_DATA',
    title: '먼저 목표 직무를 선택해 주세요',
    description: '공고 추세는 선택한 목표 직무·지역·경력 조건을 기준으로 계산합니다.',
  },
}

const FALLBACK: Readonly<Record<DataStatus, Copy>> = {
  READY: { kind: 'EMPTY', title: '표시할 결과가 없어요', description: '' },
  PREPARING: {
    kind: 'PREPARING',
    title: '결과를 준비하고 있어요',
    description: '준비되면 자동으로 표시됩니다.',
  },
  PARTIAL: {
    kind: 'PARTIAL',
    title: '일부 저장소만 분석됐어요',
    description: '분석하지 못한 저장소가 있어 결과가 달라질 수 있습니다.',
  },
  NO_DATA: {
    kind: 'NO_DATA',
    title: '표시할 데이터가 없어요',
    description: '이 조건으로 계산된 결과가 아직 없습니다.',
  },
  INSUFFICIENT_DATA: {
    kind: 'INSUFFICIENT_DATA',
    title: '판정할 근거가 부족해요',
    description: '표본이 늘어나면 다시 계산합니다.',
  },
  NOT_SUPPORTED: {
    kind: 'NOT_SUPPORTED',
    title: '아직 제공하지 않는 지표예요',
    description: '',
  },
  FAILED: {
    kind: 'ERROR',
    title: '결과를 만들지 못했어요',
    description: '잠시 후 다시 시도해 주세요.',
  },
}

function copyOf(state: ComputeState): Copy {
  return COPY[state.statusReason] ?? FALLBACK[state.dataStatus]
}

/**
 * 로딩·오류·상태를 한 자리에서 그린다.
 *
 * @returns 값을 그려도 되는 상태면 `null`. 호출부는 이 값이 `null`일 때만 본문을 그린다.
 */
export function ComputeStatePanel({
  isLoading,
  error,
  state,
  loadingLabel = '결과를 불러오는 중입니다.',
  onRetry,
}: {
  isLoading: boolean
  error: unknown
  state: ComputeState | undefined
  loadingLabel?: string
  onRetry?: () => void
}) {
  if (isLoading) {
    return <StateCard kind="LOADING" title={loadingLabel} description="" />
  }

  if (error instanceof ApiError) {
    // 목표 직무 미선택은 실패가 아니라 다음 할 일이 정해진 상태다. 서버가 그 뜻으로
    // 404 를 주고, action 이 CTA 를 가리킨다.
    const kind: StateKind = error.action === 'SHOW_EMPTY_WITH_CTA' ? 'EMPTY' : 'ERROR'
    return (
      <StateCard
        kind={kind}
        title={error.message}
        description={error.action === 'SHOW_RETRY' ? '일시적인 문제일 수 있습니다.' : ''}
        action={
          error.action === 'SHOW_RETRY' && onRetry !== undefined ? (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              다시 시도
            </button>
          ) : undefined
        }
      />
    )
  }

  if (error !== null && error !== undefined) {
    return (
      <StateCard
        kind="ERROR"
        title="결과를 불러오지 못했습니다."
        description="잠시 후 다시 시도해 주세요."
      />
    )
  }

  if (state === undefined || hasComputedValue(state)) {
    return null
  }

  const copy = copyOf(state)
  return <StateCard kind={copy.kind} title={copy.title} description={copy.description} />
}

/**
 * 부분 분석 배너.
 *
 * 값을 가리지 않고 위에 한 줄만 붙인다. 부분이라고 결과를 숨기면 있는 근거로 나온
 * 판정까지 보지 못하게 되고, 아무 표시도 없으면 완전한 결과로 오해한다.
 */
export function PartialNotice({ state }: { state: ComputeState | undefined }) {
  if (state === undefined || state.dataStatus !== 'PARTIAL') {
    return null
  }
  return (
    <p
      role="status"
      className="rounded-[14px] border border-tone-caution-bg bg-tone-caution-bg px-4 py-3 text-[12.5px] leading-[1.6] text-tone-caution"
    >
      일부 저장소를 분석하지 못해 결과가 달라질 수 있습니다. 분석하지 못한 저장소의 기술은 미판정으로
      둡니다.
    </p>
  )
}
