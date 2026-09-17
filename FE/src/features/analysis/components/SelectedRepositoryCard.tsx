import { useEffect, useMemo } from 'react'
import { Link } from 'react-router'
import type { AnalysisRequestOutcome, RepositorySummary } from '@/features/analysis/api/types'
import { BranchPicker } from '@/features/analysis/components/BranchPicker'
import { RepositoryStateBadge } from '@/features/analysis/components/RepositoryStateBadge'
import { useBranchList } from '@/features/analysis/hooks/useRepositoryAnalysis'
import { ApiError } from '@/shared/api/client'
import type { JobStatus as JobStatusValue } from '@/shared/types/domain'
import { JobStatus } from '@/shared/ui/JobStatus'

/**
 * 분석 범위 패널의 저장소 1건 · 티켓 S15P21E102-117.
 *
 * 브랜치 조회를 이 컴포넌트가 소유한다. 목록 전체가 아니라 **선택된 저장소만**
 * 조회해야 GitHub 호출이 선택 개수만큼만 발생하고, 저장소마다 브랜치가 다르므로
 * 조회 단위도 저장소여야 한다.
 *
 * 등록에 성공한 저장소는 브랜치 선택을 닫고 결과만 보여준다. 이미 서버에 접수된
 * 분석의 대상 브랜치를 화면에서 바꿀 수 있게 두면 표시와 실제가 어긋난다.
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

  const succeeded = outcome?.ok === true

  return (
    <li
      className={`rounded-[12px] border px-3.5 py-3 ${
        succeeded ? 'border-tone-success-bg bg-tone-success-bg/25' : 'border-brand-line bg-white'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13.5px] leading-[1.35] font-[750] tracking-[-0.02em] break-all text-brand-ink">
            {repository.fullName}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {repository.isPrivate && <RepositoryStateBadge state="PRIVATE" />}
            {outcome?.ok === true && (
              // BE는 와이어프레임 6종 밖의 상태도 쓴다(계약 3장, 미결 2).
              // 정의되지 않은 값이면 배지가 렌더되지 않고 아래 원문으로 확인한다.
              <JobStatus status={outcome.accepted.status as JobStatusValue} />
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

      {outcome?.ok === true ? (
        <dl className="mt-2 grid gap-1 text-[11.5px] text-brand-muted">
          <div className="flex gap-2">
            <dt className="shrink-0">분석 ID</dt>
            <dd className="font-evidence break-all text-brand-ink">
              {outcome.accepted.analysisId}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0">브랜치</dt>
            <dd className="font-evidence break-all text-brand-ink">
              {outcome.accepted.branchName} @ {outcome.accepted.commitSha.slice(0, 7)}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0">상태 원문</dt>
            <dd className="font-evidence text-brand-ink">{outcome.accepted.status}</dd>
          </div>
          {/*
            접수된 분석의 진행 화면으로 이동한다(티켓 192에서 흐름 연결).
            analysisId가 저장소마다 다르므로 링크도 카드별로 각자의 ID를 가리킨다.
            여러 저장소를 한 번에 접수해도 진행 상태는 이 링크별로 각각 확인한다.
          */}
          <Link
            to={`/analyses/${outcome.accepted.analysisId}`}
            className="mt-2 block rounded-lg bg-tone-accent px-2.5 py-2 text-center text-[12px] font-[750] text-white shadow-[0_8px_18px_rgba(47,94,235,0.2)] transition-shadow hover:shadow-[0_10px_22px_rgba(47,94,235,0.3)]"
          >
            분석 진행 화면 보기
          </Link>
        </dl>
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
