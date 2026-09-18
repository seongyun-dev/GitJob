import { useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import type { AnalysisRequestOutcome, RepositorySummary } from '@/features/analysis/api/types'
import { BranchPicker } from '@/features/analysis/components/BranchPicker'
import { RepositoryStateBadge } from '@/features/analysis/components/RepositoryStateBadge'
import { useAnalysisStatus, useBranchList } from '@/features/analysis/hooks/useRepositoryAnalysis'
import {
  analysisPhase,
  failureCopy,
  failureKind,
  hasResult,
  isPending,
  phaseCopy,
  waitedMinutes,
} from '@/features/analysis/model/analysisProgress'
import { ApiError } from '@/shared/api/client'
import { queryKeys } from '@/shared/api/queryKeys'
import type { JobStatus as JobStatusValue } from '@/shared/types/domain'
import { JobStatus } from '@/shared/ui/JobStatus'

/**
 * 분석 범위 패널의 저장소 1건 · 티켓 S15P21E102-117 · 진행 표시 S15P21E102-326.
 *
 * 브랜치 조회를 이 컴포넌트가 소유한다. 목록 전체가 아니라 **선택된 저장소만**
 * 조회해야 GitHub 호출이 선택 개수만큼만 발생하고, 저장소마다 브랜치가 다르므로
 * 조회 단위도 저장소여야 한다.
 *
 * 등록에 성공한 저장소는 브랜치 선택을 닫고 결과만 보여준다. 이미 서버에 접수된
 * 분석의 대상 브랜치를 화면에서 바꿀 수 있게 두면 표시와 실제가 어긋난다.
 *
 * ## 진행 상태를 여기서 본다 (S15P21E102-326)
 *
 * 이전에는 접수 뒤 `분석 진행 화면 보기` 링크로 `/analyses/:id`에 보냈다. 그런데 그
 * 화면이 보여 줄 수 있는 것은 "대기 / 진행 / 완료" 한 줄이 전부다 — 워커가 중간
 * 진행을 발행하지 않아 단계별 진척이 없다. 한 줄을 읽으려고 화면을 옮기게 할 이유가
 * 없어서, 고른 자리에서 끝까지 본다.
 *
 * 폴링 단위도 저장소다. 저장소마다 `analysisId`가 다르고 하나가 끝나도 다른 하나는
 * 돌고 있을 수 있어, 카드가 자기 분석만 본다.
 *
 * `/analyses/:id`는 주소로 직접 들어오는 경로로 남아 있고, 문구와 판정은
 * `model/analysisProgress`를 함께 써서 두 화면이 같은 말을 한다.
 */
export function SelectedRepositoryCard({
  repository,
  branchName,
  outcome,
  onBranchChange,
  onRemove,
}: {
  repository: RepositorySummary
  branchName: string
  outcome: AnalysisRequestOutcome | undefined
  onBranchChange: (fullName: string, branch: string) => void
  onRemove: (fullName: string) => void
}) {
  const branches = useBranchList(repository.fullName)
  const items = branches.data?.items

  /**
   * 사용자가 고른 값이 목록에 있으면 유지하고, 없으면 기본 브랜치 → 첫 항목 순으로 정한다.
   * 브랜치가 100개를 넘는 저장소는 기본 브랜치가 첫 페이지에 없을 수 있어 첫 항목까지 본다.
   */
  const effectiveBranch = useMemo(() => {
    if (items === undefined || items.length === 0) {
      return ''
    }
    if (branchName !== '' && items.some((branch) => branch.name === branchName)) {
      return branchName
    }
    if (items.some((branch) => branch.name === repository.defaultBranch)) {
      return repository.defaultBranch
    }
    return items[0]?.name ?? ''
  }, [items, branchName, repository.defaultBranch])

  /**
   * 확정된 브랜치를 부모에 올린다. 요청 본문을 만드는 쪽은 부모이고, 브랜치 목록은
   * 여기서만 알기 때문이다. 부모가 같은 값을 갖게 되면 조건이 거짓이 되어 멈춘다.
   */
  useEffect(() => {
    if (effectiveBranch !== '' && effectiveBranch !== branchName) {
      onBranchChange(repository.fullName, effectiveBranch)
    }
  }, [effectiveBranch, branchName, onBranchChange, repository.fullName])

  const accepted = outcome?.ok === true ? outcome.accepted : null

  /*
   * 접수된 분석만 폴링한다. `useAnalysisStatus`는 id가 없으면 스스로 쉬고, 종료
   * 상태가 되면 서버가 `pollAfterSeconds`를 null로 줘서 폴링이 멈춘다.
   */
  const status = useAnalysisStatus(accepted?.analysisId)

  /*
   * 접수 응답의 `status`는 접수 시점 값이라 곧 낡는다. 폴링 값이 있으면 그것을
   * 쓰고, 첫 응답이 오기 전에는 접수 값으로 버틴다.
   */
  const phase = analysisPhase(status.data?.analysisStatus ?? accepted?.status ?? 'QUEUED')

  /*
   * 분석이 끝나면 내 기술 목록을 다시 읽게 한다. 결과를 보러 갔을 때 이전 분석의
   * 목록이 남아 있으면 방금 끝난 분석이 아무것도 못 찾은 것처럼 보인다.
   */
  const queryClient = useQueryClient()
  useEffect(() => {
    if (hasResult(phase)) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myTechnologies() })
    }
  }, [phase, queryClient])

  /*
   * 카드 색은 **분석이 어떻게 됐는지**를 따른다. 전에는 "등록에 성공했는지"를 따라
   * 접수되자마자 초록이 됐는데, 그러면 아직 시작도 하지 않은 분석이 끝난 것처럼
   * 보인다. 초록은 결과가 나왔을 때만 쓴다.
   */
  const cardTone =
    accepted === null
      ? 'border-brand-line bg-white'
      : phase === 'FAILED'
        ? 'border-tone-danger-bg bg-tone-danger-bg/20'
        : hasResult(phase)
          ? 'border-tone-success-bg bg-tone-success-bg/25'
          : 'border-brand-line bg-white'

  return (
    <li className={`rounded-[12px] border px-3.5 py-3 ${cardTone}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13.5px] leading-[1.35] font-[750] tracking-[-0.02em] break-all text-brand-ink">
            {repository.fullName}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {repository.isPrivate && <RepositoryStateBadge state="PRIVATE" />}
            {accepted !== null && (
              // BE는 와이어프레임 6종 밖의 상태도 쓴다(계약 3장, 미결 2).
              // 정의되지 않은 값이면 배지가 렌더되지 않고 아래 진행 블록으로 확인한다.
              <JobStatus
                status={(status.data?.analysisStatus ?? accepted.status) as JobStatusValue}
              />
            )}
            {outcome?.ok === false && <RepositoryStateBadge state="REQUEST_FAILED" />}
          </div>
        </div>
        {/*
          등록에 성공한 저장소에도 제거를 남긴다. 목록의 checkbox로 어차피 해제할 수 있어
          여기서만 숨기면 실제 보호는 못 하면서 두 컨트롤만 어긋난다.
          제거는 선택 목록에서 빼는 동작이고 서버의 분석을 취소하지 않는다.
        */}
        <button
          type="button"
          onClick={() => onRemove(repository.fullName)}
          className="shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] text-brand-faint hover:bg-neutral-100 hover:text-brand-muted"
        >
          제거
        </button>
      </div>

      {accepted !== null ? (
        <div className="mt-2 grid gap-2">
          <p className="font-evidence text-[11.5px] break-all text-brand-muted">
            {accepted.branchName} @ {accepted.commitSha.slice(0, 7)}
          </p>

          <AnalysisPhaseBlock
            phase={phase}
            requestedAt={status.data?.requestedAt ?? null}
            errorCode={status.data?.errorCode ?? null}
            unreachable={status.isError}
          />
        </div>
      ) : (
        <div className="mt-2.5">
          <BranchPicker
            inputId={`branch-${repository.githubRepositoryId}`}
            branches={items}
            value={effectiveBranch}
            onChange={(branch) => onBranchChange(repository.fullName, branch)}
            isLoading={branches.isPending}
            error={branches.error}
            onRetry={() => void branches.refetch()}
          />
          {outcome?.ok === false && (
            <p className="mt-2 text-[11.5px] leading-[1.5] text-tone-danger">
              {outcome.error instanceof ApiError
                ? `${outcome.error.message} (코드 ${outcome.error.code})`
                : '요청을 처리할 수 없습니다.'}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * 분석 한 건의 진행 표시 · 티켓 S15P21E102-326.
 *
 * 패널 폭(372px) 안에 들어가야 해서 `StateCard`를 쓰지 않고 카드 안쪽 전용으로
 * 짧게 그린다. 문구와 판정은 `model/analysisProgress`가 가지고 있어
 * `/analyses/:analysisId`와 같은 말을 한다.
 */
function AnalysisPhaseBlock({
  phase,
  requestedAt,
  errorCode,
  unreachable,
}: {
  phase: ReturnType<typeof analysisPhase>
  requestedAt: string | null
  errorCode: string | null
  unreachable: boolean
}) {
  /*
   * 상태를 못 읽는 것과 분석이 실패한 것은 다르다. 폴링이 막혀 있을 뿐 서버에서는
   * 분석이 계속 돌고 있을 수 있어, 실패라고 말하지 않는다.
   */
  if (unreachable) {
    return (
      <p className="rounded-lg bg-tone-neutral-bg px-2.5 py-2 text-[11.5px] leading-[1.5] text-brand-muted">
        진행 상태를 읽지 못했습니다. 분석은 서버에서 계속 진행됩니다.
      </p>
    )
  }

  const copy = phaseCopy(phase)

  if (phase === 'FAILED') {
    const failure = failureCopy(failureKind(errorCode))
    return (
      <div className="rounded-lg bg-tone-danger-bg/40 px-2.5 py-2">
        <p className="text-[12px] font-[750] text-tone-danger">{failure.title}</p>
        <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-muted">{failure.description}</p>
        {failureKind(errorCode) === 'GITHUB_RECONNECT' && (
          <Link
            to="/onboarding/github?redirectTo=/onboarding/repositories"
            className="mt-1.5 inline-block text-[11.5px] font-semibold text-tone-accent underline"
          >
            GitHub 다시 연결
          </Link>
        )}
        {errorCode !== null && (
          <p className="mt-1.5 font-evidence text-[11px] text-brand-faint">코드 {errorCode}</p>
        )}
      </div>
    )
  }

  if (hasResult(phase)) {
    return (
      <div>
        <p className="text-[12px] font-[750] text-tone-success">
          <span aria-hidden>✓ </span>
          {copy.title}
        </p>
        <Link
          to="/evidence"
          className="mt-1.5 block rounded-lg bg-tone-accent px-2.5 py-2 text-center text-[12px] font-[750] text-white shadow-[0_8px_18px_rgba(47,94,235,0.2)] transition-shadow hover:shadow-[0_10px_22px_rgba(47,94,235,0.3)]"
        >
          결과 확인하러 가기
        </Link>
      </div>
    )
  }

  const waited = requestedAt === null ? null : waitedMinutes(requestedAt)

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-lg px-2.5 py-2 ${
        phase === 'RUNNING' ? 'bg-tone-accent-bg/40' : 'bg-tone-neutral-bg'
      }`}
    >
      <p className="flex items-center gap-1.5 text-[12px] font-[750] text-brand-ink">
        {/*
          진행 중일 때만 움직인다. 대기 중에는 아무 일도 일어나지 않으므로 움직이는
          표시를 두면 진행되고 있다는 인상을 준다.
        */}
        <span
          aria-hidden
          className={`size-1.5 shrink-0 rounded-full ${
            phase === 'RUNNING' ? 'bg-tone-accent motion-safe:animate-pulse' : 'bg-brand-faint'
          }`}
        />
        {copy.title}
      </p>
      <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-muted">{copy.description}</p>
      {/*
        경과 시간은 사실이라 적는다. 남은 시간은 알 수 없어 적지 않는다.
        워커가 내려가 있으면 이 숫자만 늘어나고, 그것이 지금 화면이 말할 수 있는 전부다.
      */}
      {isPending(phase) && waited !== null && (
        <p className="mt-1 text-[11px] text-brand-faint tabular-nums">요청 후 {waited}분 경과</p>
      )}
    </div>
  )
}
