import { useCallback, useState } from 'react'
import type { AnalysisRequestOutcome, RepositorySummary } from '@/features/analysis/api/types'
import { AnalysisRequestPanel } from '@/features/analysis/components/AnalysisRequestPanel'
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
} from '@/features/analysis/components/QueryStatePanel'
import { RepositoryListItem } from '@/features/analysis/components/RepositoryListItem'
import {
  useAnalysisRequests,
  useRepositoryList,
} from '@/features/analysis/hooks/useRepositoryAnalysis'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { DESIGN_FIXTURES_ENABLED } from '@/mocks/designFixtures'
import { REPOSITORY_LIST } from '@/mocks/fixtures/repositoryList'

/**
 * S3 분석 대상 저장소 선택 · 티켓 S15P21E102-117.
 *
 * 시각 기준은 `GitJob Desktop UI Final.html`의 `section#repos`다. computed style에서
 * 읽은 값을 그대로 쓴다.
 *   내부 콘텐츠 1232px · grid 846px + 372px · gap 14px · align start
 *   eyebrow 11px/800 #2F5EEB ls 1.76px · 제목 34px/750 ls -1.53px · 설명 14px/23.1px
 *
 * Final에 있으나 넣지 않은 것과 이유(실제 데이터가 없으면 만들지 않는다):
 *   - 헤더 네비게이션·`마지막 분석 오늘 10:42`: 라우트와 API가 없다(AppHeader 주석).
 *   - `Fork` · `Archived` 배지와 그 안내문: BE 응답에 fork 플래그가 없고 archived·disabled
 *     구분도 없다. `analyzable` 한 값만 온다.
 *   - 저장소별 언어 여러 개: 응답의 `language`는 대표 언어 한 개다.
 *   - `최근 push`: 응답에 `pushed_at`이 없어 `updatedAt`을 "갱신"으로 정확히 표기한다.
 *
 * 확정된 분석 구조(2026-09-09): 사용자는 저장소 여러 개를 고르고, 저장소마다
 * 독립적으로 분석하며 `analysisId`도 저장소마다 따로 생긴다. 그래서 화면은
 * 다중 선택이지만 요청은 저장소 수만큼의 단건 호출이다.
 *
 * 구현된 계약만 쓴다.
 *   `GET  /me/repositories`                              목록
 *   `GET  /me/repositories/{owner}/{repo}/branches`       브랜치 (선택된 저장소만)
 *   `POST /analyses`                                      분석 등록 (저장소당 1회)
 */

/** 전체 개수를 주지 않는 계약이라 페이지 번호만 보여주고 총 페이지 수는 만들지 않는다. */
function Pagination({
  page,
  hasNext,
  disabled,
  onChange,
}: {
  page: number
  hasNext: boolean
  disabled: boolean
  onChange: (next: number) => void
}) {
  const buttonClass =
    'rounded-xl border border-brand-line bg-white px-4 py-2 text-[13px] font-medium text-brand-muted shadow-[0_10px_28px_rgba(25,47,81,0.07)] hover:border-brand-line-active hover:text-brand-ink disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-brand-line'

  return (
    <nav className="mt-3.5 flex items-center justify-between gap-2" aria-label="저장소 목록 페이지">
      <button
        type="button"
        className={buttonClass}
        disabled={disabled || page <= 1}
        onClick={() => onChange(page - 1)}
      >
        이전
      </button>
      <span className="text-[12.5px] text-brand-faint">{page} 페이지</span>
      <button
        type="button"
        className={buttonClass}
        disabled={disabled || !hasNext}
        onClick={() => onChange(page + 1)}
      >
        다음
      </button>
    </nav>
  )
}

export function RepositorySelectionPage() {
  const [page, setPage] = useState(1)
  /**
   * fullName만 담지 않고 항목 전체를 담는다. 페이지를 넘기면 현재 페이지 목록에서
   * 선택한 저장소가 사라지는데, 선택 요약과 브랜치 선택은 계속 보여야 한다.
   * Map이라 선택 순서가 보존되고 fullName으로 바로 조회된다.
   */
  const [selected, setSelected] = useState<Map<string, RepositorySummary>>(new Map())
  const [branchByRepo, setBranchByRepo] = useState<Map<string, string>>(new Map())
  const [outcomes, setOutcomes] = useState<Map<string, AnalysisRequestOutcome>>(new Map())

  const repositories = useRepositoryList(page)
  const submission = useAnalysisRequests()

  /*
   * 디자인 fixture가 켜져 있으면 목록을 서버에서 보지 않는다. 이 화면의 목록은 BE와
   * GitHub OAuth 연결이 모두 살아 있어야 채워지는데, 레이아웃을 잡는 동안 둘을 띄워
   * 두는 비용이 크다.
   *
   * `withDesignFixture`를 쓰지 않고 직접 분기하는 이유는 대체해야 하는 것이 값 하나가
   * 아니라 **조회 상태 전체**이기 때문이다. 값만 갈아끼우면 fixture 목록과 오류 패널이
   * 함께 보여 무엇을 보고 있는지 알 수 없다.
   */
  const items = DESIGN_FIXTURES_ENABLED ? REPOSITORY_LIST : repositories.data?.items
  const showQueryState = !DESIGN_FIXTURES_ENABLED
  const selectedList = [...selected.values()]

  /** 선택 해제 시 그 저장소의 브랜치·결과까지 함께 정리한다. 남겨 두면 재선택 때 되살아난다. */
  const removeRepository = useCallback((fullName: string) => {
    setSelected((prev) => {
      const next = new Map(prev)
      next.delete(fullName)
      return next
    })
    setBranchByRepo((prev) => {
      const next = new Map(prev)
      next.delete(fullName)
      return next
    })
    setOutcomes((prev) => {
      const next = new Map(prev)
      next.delete(fullName)
      return next
    })
  }, [])

  function toggleRepository(fullName: string) {
    if (selected.has(fullName)) {
      removeRepository(fullName)
      return
    }
    const found = items?.find((repository) => repository.fullName === fullName)
    if (found === undefined) {
      return
    }
    setSelected((prev) => new Map(prev).set(fullName, found))
  }

  /**
   * 카드가 확정한 브랜치를 받는다. 값이 같으면 이전 Map을 그대로 돌려주어
   * 카드의 동기화 effect가 다시 도는 것을 막는다.
   */
  const handleBranchChange = useCallback((fullName: string, branch: string) => {
    setBranchByRepo((prev) => {
      if (prev.get(fullName) === branch) {
        return prev
      }
      return new Map(prev).set(fullName, branch)
    })
  }, [])

  function startAnalysis() {
    const targets = selectedList
      // 이미 접수된 저장소는 다시 보내지 않는다. 재시도 대상은 미시도 + 실패뿐이다.
      .filter((repository) => outcomes.get(repository.fullName)?.ok !== true)
      .map((repository) => ({
        repositoryFullName: repository.fullName,
        branchName: branchByRepo.get(repository.fullName) ?? '',
      }))
      .filter((target) => target.branchName !== '')

    if (targets.length === 0) {
      return
    }

    submission.mutate(targets, {
      onSuccess: (results) => {
        setOutcomes((prev) => {
          const next = new Map(prev)
          for (const result of results) {
            next.set(result.target.repositoryFullName, result)
          }
          return next
        })
      },
    })
  }

  return (
    <div>
      <header className="max-w-[640px]">
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">REPOSITORY</p>
          <DesignMockBadge />
        </div>
        <h1 className="mt-2 text-[26px] leading-[1.16] font-[750] tracking-[-0.045em] text-brand-ink sm:text-[30px] lg:text-[34px]">
          분석할 프로젝트를 선택해주세요
        </h1>
        <p className="mt-3 text-[14px] leading-[1.65] text-brand-muted">
          선택한 Repository의 파일 · 설정 · Commit을 읽기 전용으로 분석합니다. 언제든 다시 선택해
          재분석할 수 있습니다.
        </p>
        <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-faint">
          비공개 Repository도 같은 기준으로 분석하며, 임시 checkout은 분석 후 삭제하고 공개 Trend에
          포함하지 않습니다.
        </p>
      </header>

      <div className="gj-split mt-7">
        <section aria-labelledby="repository-list-heading">
          <h2 id="repository-list-heading" className="sr-only">
            저장소 목록
          </h2>

          {showQueryState && repositories.isPending && (
            <LoadingPanel label="저장소 목록을 불러오는 중입니다." />
          )}

          {showQueryState && repositories.isError && (
            <ErrorPanel error={repositories.error} onRetry={() => void repositories.refetch()} />
          )}

          {items !== undefined && items.length === 0 && (
            <EmptyPanel
              title="분석할 수 있는 저장소가 없습니다."
              description="GitHub에 저장소를 만들거나, 연결한 계정의 접근 권한을 확인해 주세요."
            />
          )}

          {items !== undefined && items.length > 0 && (
            <>
              <ul className="grid gap-2.5">
                {items.map((repository) => (
                  <RepositoryListItem
                    key={repository.githubRepositoryId}
                    repository={repository}
                    selected={selected.has(repository.fullName)}
                    onToggle={toggleRepository}
                  />
                ))}
              </ul>
              {/* fixture 목록에는 다음 페이지가 없다. 누를 수 없는 컨트롤을 두지 않는다. */}
              {showQueryState && (
                <Pagination
                  page={page}
                  hasNext={repositories.data?.hasNext ?? false}
                  disabled={repositories.isFetching}
                  onChange={setPage}
                />
              )}
            </>
          )}
        </section>

        <AnalysisRequestPanel
          repositories={selectedList}
          branchByRepo={branchByRepo}
          outcomes={outcomes}
          isSubmitting={submission.isPending}
          onBranchChange={handleBranchChange}
          onRemove={removeRepository}
          onSubmit={startAnalysis}
        />
      </div>
    </div>
  )
}
