import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { AnalysisStepList } from '@/features/analysis/components/AnalysisStepList'
import { useAnalysisStatus } from '@/features/analysis/hooks/useRepositoryAnalysis'
import {
  analysisPhase,
  failureCopy,
  failureKind,
  hasResult,
  isPending,
  phaseCopy,
  phaseHeadline,
  waitedMinutes,
} from '@/features/analysis/model/analysisProgress'
import { profileErrorMessage } from '@/features/evidence/hooks/useTechnologyProfile'
import { DataRegion } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'
import { queryKeys } from '@/shared/api/queryKeys'

/**
 * 분석 진행 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `07 Analysis Progress`).
 *
 * v2 구조: hero → 진행 영역(단계 4칸) + 우측 `PARTIAL RESULT` 패널(958/372).
 * 단계 목록은 `AnalysisStepList`로 옮겨 이 페이지는 배치만 맡는다.
 *
 * 진행 상태는 `GET /analyses/{analysisId}`에서 읽는다. 다음 호출 간격은 서버가
 * 주는 `pollAfterSeconds`를 따르고, 종료 상태면 BE가 null 을 줘서 폴링이 멈춘다.
 *
 * 남은 시간을 표시하지 않는다. 워커가 중간 진행을 발행하지 않아 지금은 저장소
 * 단위 0% 또는 100%만 나오고, 그 위에서 시간을 추정하면 지어낸 값이 된다. v2 의
 * `72%`·`약 1분 남음`은 아트보드의 demo 값이다.
 *
 * v2 hero 우측의 `상태 미리보기 · 진행 중 · RATE_LIMITED`는 아트보드에서 상태를
 * 바꿔 보기 위한 디자인 도구 장치이지 제품 컨트롤이 아니라 옮기지 않는다.
 *
 * URL의 `analysisId`는 실제 route state지만 화면의 주요 정보가 아니라 각주로 둔다.
 *
 * ## 주 흐름에서는 더 이상 여기로 오지 않는다 (S15P21E102-326)
 *
 * 저장소를 고른 뒤 진행과 완료를 선택 화면의 패널 안에서 보여주도록 바꿨다. 이 화면이
 * 보여 줄 수 있는 것이 "대기 / 진행 / 완료" 한 줄이라 화면을 옮길 값어치가 없었다.
 *
 * 그래도 주소는 남긴다. BE가 접수 응답으로 `statusUrl`을 주고, 새로고침이나 링크로
 * 직접 들어오는 경로가 있어야 한다. 상태 판정과 문구는 패널과 같은
 * `model/analysisProgress`를 써서 두 곳이 같은 말을 한다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-136(이윤서)에 있다. 시각 적용까지만 한다.
 */
export function AnalysisProgressPage() {
  const { analysisId } = useParams()
  const queryClient = useQueryClient()
  const status = useAnalysisStatus(analysisId)
  const data = status.data

  /*
   * 상태를 아직 못 읽었으면 국면을 정하지 않는다. 기본값을 두면 로딩 중에 hero가
   * 한 번 엉뚱한 제목을 보였다가 바뀐다.
   */
  const phase = data === undefined ? null : analysisPhase(data.analysisStatus)

  useEffect(() => {
    if (phase !== null && hasResult(phase)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myTechnologies() })
    }
  }, [phase, queryClient])

  const hero = phase === null ? null : phaseCopy(phase)

  return (
    <div>
      <PageHero
        title={phase === null ? '분석 상태' : phaseHeadline(phase)}
        description={hero?.description ?? '진행 상태를 읽고 있습니다.'}
      />

      <div className="gj-split mt-7">
        <DataRegion
          title="분석 진행"
        >
          <AnalysisStepList />
          <div className="mt-3">
            <ProgressState
              loading={status.isPending}
              error={status.isError ? profileErrorMessage(status.error) : null}
              data={data}
            />
          </div>
        </DataRegion>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            PARTIAL RESULT
          </p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            지금까지 확인된 기술
          </h2>
          <Link
            to="/evidence"
            className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            내 기술 보기
          </Link>
          <Link
            to="/onboarding/repositories"
            className="mt-2 block rounded-xl px-4 py-2.5 text-center text-[13px] text-brand-muted hover:text-brand-ink"
          >
            저장소 다시 선택
          </Link>
        </aside>
      </div>
    </div>
  )
}

/**
 * 상태 한 줄.
 *
 * 대기(`QUEUED`)와 진행(`RUNNING`)을 구분한다. 전에는 둘을 하나의 fallback으로 묶어
 * 아직 시작되지 않은 분석에도 "분석하고 있어요"라고 말했다 — 워커가 내려가 있으면
 * 그 문장이 몇 분이든 유지된다.
 */
function ProgressState({
  loading,
  error,
  data,
}: {
  loading: boolean
  error: string | null
  data:
    | {
        analysisStatus: string
        currentStage: string
        completedCount: number
        totalCount: number
        requestedAt: string
        errorCode: string | null
      }
    | undefined
}) {
  if (loading) {
    return <StateCard kind="LOADING" title="상태를 읽는 중" description="잠시만 기다려 주세요." />
  }
  if (error !== null) {
    return <StateCard kind="ERROR" title="진행 상태를 불러오지 못했어요" description={error} />
  }
  if (data === undefined) {
    return null
  }

  const phase = analysisPhase(data.analysisStatus)
  const copy = phaseCopy(phase)
  const scope = `저장소 ${data.completedCount}/${data.totalCount}`

  if (phase === 'FAILED') {
    const kind = failureKind(data.errorCode)
    const failure = failureCopy(kind)
    return (
      <StateCard
        kind="ERROR"
        title={failure.title}
        description={failure.description}
        meta={data.errorCode ?? undefined}
        action={failureAction(kind)}
      />
    )
  }

  if (hasResult(phase)) {
    return (
      <StateCard
        kind={copy.kind}
        title={copy.title}
        description={copy.description}
        meta={scope}
        action={
          <Link to="/evidence" className="text-tone-accent underline">
            결과 확인하러 가기
          </Link>
        }
      />
    )
  }

  /*
   * 대기·진행 중에는 경과 시간만 덧붙인다. 남은 시간은 알 수 없어 적지 않는다.
   * `저장소 0/1`은 이 국면에서 늘 0이라 알려 주는 것이 없어 빼고, 대신 얼마나
   * 기다렸는지를 둔다.
   */
  const waited = isPending(phase) ? waitedMinutes(data.requestedAt) : null

  return (
    <StateCard
      kind={copy.kind}
      title={copy.title}
      description={copy.description}
      meta={waited === null ? undefined : `요청 후 ${waited}분 경과`}
    />
  )
}

/** 실패 사유별 복구 경로. 문구는 `model/analysisProgress`가 갖고 링크만 여기서 만든다. */
function failureAction(kind: ReturnType<typeof failureKind>) {
  if (kind === 'GITHUB_RECONNECT') {
    return (
      <Link
        to="/onboarding/github?redirectTo=/onboarding/repositories"
        className="text-tone-accent underline"
      >
        GitHub 다시 연결
      </Link>
    )
  }
  if (kind === 'REPOSITORY') {
    return (
      <Link to="/onboarding/repositories" className="text-tone-accent underline">
        저장소 다시 선택
      </Link>
    )
  }
  return undefined
}
