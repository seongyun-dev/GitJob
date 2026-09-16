import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { AnalysisStepList } from '@/features/analysis/components/AnalysisStepList'
import { useAnalysisStatus } from '@/features/analysis/hooks/useRepositoryAnalysis'
import { profileErrorMessage } from '@/features/evidence/hooks/useTechnologyProfile'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
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
 * 이 화면의 기능 ownership은 S15P21E102-136(이윤서)에 있다. 시각 적용까지만 한다.
 */
export function AnalysisProgressPage() {
  const { analysisId } = useParams()
  const queryClient = useQueryClient()
  const status = useAnalysisStatus(analysisId)
  const data = status.data

  useEffect(() => {
    if (data?.analysisStatus === 'SUCCEEDED' || data?.analysisStatus === 'PARTIAL_SUCCEEDED') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myTechnologies() })
    }
  }, [data?.analysisStatus, queryClient])

  return (
    <div>
      <PageHero
        eyebrow="ANALYSIS"
        title="GitHub를 분석하고 있어요"
        description="선택한 Repository를 순서대로 분석합니다. 이 화면을 벗어나도 분석은 계속됩니다."
      />

      <div className="gj-split mt-7">
        <DataRegion
          eyebrow="PROGRESS"
          title="분석 진행"
          hint="네 단계를 순서대로 거칩니다. 어디까지 진행됐는지는 상태 조회가 붙으면 표시됩니다."
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
          <div className="mt-4">
            <StateCard
              kind="PREPARING"
              title="중간 결과 준비 중"
              description="분석이 진행되는 동안 확인된 기술이 이 자리에 쌓입니다. 추정값으로 채우지 않습니다."
            />
          </div>
          <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-muted">
            Personal Level은 사용자 기여 확인 단계가 끝나야 확정됩니다. 중간 결과는 Repository
            기준입니다.
          </p>
          <Link
            to="/evidence"
            className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            Evidence 화면 보기
          </Link>
          <Link
            to="/onboarding/repositories"
            className="mt-2 block rounded-xl px-4 py-2.5 text-center text-[13px] text-brand-muted hover:text-brand-ink"
          >
            저장소 다시 선택
          </Link>
        </aside>
      </div>

      {analysisId !== undefined && (
        <PageFootnote>
          분석 ID <span className="font-evidence text-brand-muted">{analysisId}</span> · 이 화면을
          벗어나도 분석은 서버에서 계속 진행됩니다.
        </PageFootnote>
      )}
    </div>
  )
}

/** 상태 한 줄. 종료됐는지, 실패했는지, 아직 도는지를 구분한다. */
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

  const scope = `저장소 ${data.completedCount}/${data.totalCount}`

  if (data.analysisStatus === 'FAILED') {
    const failure = analysisFailure(data.errorCode)
    return (
      <StateCard
        kind="ERROR"
        title={failure.title}
        description={failure.description}
        meta={data.errorCode ?? data.currentStage}
        action={failure.action}
      />
    )
  }
  if (data.analysisStatus === 'SUCCEEDED' || data.analysisStatus === 'PARTIAL_SUCCEEDED') {
    return (
      <StateCard
        kind={data.analysisStatus === 'SUCCEEDED' ? 'EMPTY' : 'PARTIAL'}
        title="분석이 끝났어요"
        description="확인된 기술과 근거를 보러 갈 수 있습니다."
        meta={scope}
        action={
          <Link to="/evidence" className="text-tone-accent underline">
            결과 보기
          </Link>
        }
      />
    )
  }
  return (
    <StateCard
      kind="LOADING"
      title="분석하고 있어요"
      description="이 화면을 벗어나도 분석은 계속됩니다."
      meta={`${data.currentStage} · ${scope}`}
    />
  )
}

function analysisFailure(errorCode: string | null) {
  if (errorCode === 'GITHUB_RECONNECT_REQUIRED') {
    return {
      title: 'GitHub 연결을 갱신해 주세요',
      description: '비공개 저장소 권한이 만료되었거나 조직 승인이 필요합니다.',
      action: (
        <Link to="/onboarding/github?redirectTo=/onboarding/repositories" className="text-tone-accent underline">
          GitHub 다시 연결
        </Link>
      ),
    }
  }
  if (
    errorCode === 'REPOSITORY_NOT_ACCESSIBLE' ||
    errorCode === 'REPOSITORY_CREDENTIAL_NOT_FOUND'
  ) {
    return {
      title: '저장소에 접근할 수 없어요',
      description: '저장소가 삭제되었거나 현재 GitHub 계정의 접근 권한이 바뀌었습니다.',
      action: (
        <Link to="/onboarding/repositories" className="text-tone-accent underline">
          저장소 다시 선택
        </Link>
      ),
    }
  }
  if (
    errorCode === 'CREDENTIAL_BROKER_UNAVAILABLE' ||
    errorCode === 'CREDENTIAL_BROKER_INVALID_RESPONSE' ||
    errorCode === 'CREDENTIAL_BROKER_UNAUTHORIZED'
  ) {
    return {
      title: '비공개 저장소 연결이 지연되고 있어요',
      description: '서비스 연결을 복구한 뒤 다시 분석해 주세요.',
      action: undefined,
    }
  }
  return {
    title: '분석에 실패했어요',
    description: '아래 사유를 확인하고 다시 시도해 주세요.',
    action: undefined,
  }
}
