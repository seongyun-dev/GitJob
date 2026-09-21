import type {
  AnalysisRequestOutcome,
  LatestBatch,
  LatestBatchItem,
  RepositorySummary,
} from '@/features/analysis/api/types'
import { SelectedRepositoryCard } from '@/features/analysis/components/SelectedRepositoryCard'
import {
  batchMarks,
  batchProgressLabel,
  showResetPrompt,
} from '@/features/analysis/model/analysisBatch'
import { SegmentBar } from '@/shared/ui/MeterBar'

/**
 * 분석 범위 패널 · 티켓 S15P21E102-117.
 *
 * 치수·색·문구는 `GitJob Desktop UI Final.html`의 `ANALYSIS SCOPE` 패널(`aside`)
 * computed style을 그대로 옮겼다.
 *   width 372px · padding 22px · radius 18px · 흰 배경 · border 1px #E0E7F1
 *   shadow rgba(25,47,81,0.07) 0 10px 28px
 *   eyebrow 11px/800 #2F5EEB ls 1.76px · 제목 18px/750 ls -0.54px #101A2E
 *   근거 항목 13.5px #465873 padding 12px 0 gap 12px
 *   CTA 14px/750 padding 14px 22px radius 12px · shadow rgba(47,94,235,0.24) 0 12px 26px
 *   각주 12.5px #7C8A9E margin-top 12px
 *
 * Final의 패널에는 선택한 저장소 목록과 브랜치 selector가 없다. 하지만 저장소마다
 * 브랜치를 정해 보내는 것은 이 티켓의 기능 요구라서 유지하고, Final의 시각 언어로
 * 스타일만 맞췄다. Final의 기능을 베끼지 않고 시각만 가져온다는 원칙에 따른 것이다.
 *
 * ## 접수 뒤에도 이 화면에 머문다 (S15P21E102-326)
 *
 * 이전에는 접수 뒤 `분석 진행 화면 보기`로 `/analyses/:id`에 보냈다. 그 화면이 보여
 * 줄 수 있는 것은 "대기 / 진행 / 완료" 한 줄이 전부여서 — 워커가 중간 진행을
 * 발행하지 않아 단계별 진척이 없다 — 화면을 옮길 값어치가 없었다. 이제 진행과 완료를
 * 저장소 카드 안에서 보여주고, 결과가 나오면 카드의 버튼으로 바로 결과로 간다.
 *
 * 저장소마다 분석이 독립적이라 상태는 카드마다 다르다. 패널은 그 위에 묶음 전체를
 * 한 줄로 말한다 -- "4개 중 2개 완료".
 *
 * ## 퍼센트를 만들지 않는다 (S15P21E102-136)
 *
 * 서버가 아는 것은 끝난 개수 하나뿐이고, 남은 저장소가 얼마나 걸릴지는 저장소마다
 * 다르다. `2/4`는 사실이고 `50%`는 그 사실을 시간처럼 보이게 만든 값이다. 그래서
 * 막대도 비율이 아니라 저장소마다 칸 하나인 `SegmentBar`를 쓴다 -- 4개 중 3개와
 * 8개 중 6개는 같은 75%라도 다른 상황이다.
 */

/** Final CTA의 그라디언트·그림자 값. */
const PRIMARY_CTA =
  'w-full rounded-xl bg-[linear-gradient(135deg,var(--color-brand-600),var(--color-brand-400))] px-[22px] py-[14px] text-[14px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)] transition-shadow not-disabled:hover:shadow-[0_16px_32px_rgba(47,94,235,0.34)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none'

export function AnalysisRequestPanel({
  repositories,
  branchByRepo,
  outcomes,
  isSubmitting,
  batch,
  itemByRepository,
  blockedReason,
  selectionNotice,
  submitFailure,
  dismissedBatchId,
  onBranchChange,
  onRemove,
  onSubmit,
  onReset,
}: {
  repositories: RepositorySummary[]
  branchByRepo: Map<string, string>
  outcomes: Map<string, AnalysisRequestOutcome>
  isSubmitting: boolean
  /** 서버가 아는 현재 묶음. 없으면 아직 아무것도 돌고 있지 않다 */
  batch: LatestBatch | null
  itemByRepository: Map<string, LatestBatchItem>
  /** 제출을 막아야 하는 이유. 없으면 null이고 CTA가 살아 있다 */
  blockedReason: string | null
  /** 선택 상한에 닿았을 때의 안내. 닿지 않았으면 null */
  selectionNotice: string | null
  /** 요청 전체가 거절됐을 때의 사유. 항목별 실패와 달리 예외로만 오는 값이다 */
  submitFailure: string | null
  dismissedBatchId: string | null
  onBranchChange: (fullName: string, branch: string) => void
  onRemove: (fullName: string) => void
  onSubmit: () => void
  onReset: () => void
}) {
  const succeeded = repositories.filter(
    (repository) => outcomes.get(repository.fullName)?.ok === true,
  )
  const failed = repositories.filter(
    (repository) => outcomes.get(repository.fullName)?.ok === false,
  )
  const untried = repositories.filter(
    (repository) => outcomes.get(repository.fullName) === undefined,
  )

  /** 이미 접수된 저장소는 다시 보내지 않는다. 재요청 대상은 미시도 + 실패뿐이다. */
  const submittable = [...untried, ...failed]

  /** 브랜치가 확정되지 않은 대상이 하나라도 있으면 보내지 않는다. 서버가 필수로 요구한다. */
  const branchesReady = submittable.every((repository) => {
    const branch = branchByRepo.get(repository.fullName)
    return branch !== undefined && branch !== ''
  })

  const isRetry = untried.length === 0 && failed.length > 0
  const canSubmit =
    submittable.length > 0 && branchesReady && !isSubmitting && blockedReason === null

  /** 보낼 것이 남지 않았고 접수된 것이 있으면, 이제 볼 곳은 각 저장소 카드다. */
  const allSubmitted = submittable.length === 0 && succeeded.length > 0

  const progressLabel = batchProgressLabel(batch)
  const canReset = showResetPrompt(batch, dismissedBatchId)

  return (
    <section
      id="analysis-request-panel"
      aria-labelledby="analysis-request-heading"
      className="scroll-mt-32 rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:sticky lg:top-[96px]"
    >
      <h2
        id="analysis-request-heading"
        className="text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink"
      >
        선택한 저장소 {repositories.length}개
      </h2>

      {progressLabel !== null && batch !== null && (
        <div className="mt-3">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-[13px] font-[750] text-brand-ink">{progressLabel}</p>
            <p className="text-[11.5px] text-brand-faint">저장소 {batch.totalCount}개</p>
          </div>
          <div className="mt-2">
            <SegmentBar marks={batchMarks(batch)} />
          </div>
        </div>
      )}

      {repositories.length === 0 ? (
        // 패널은 항상 자리를 지킨다. Final에서도 ANALYSIS SCOPE 블록이 화면의 고정 요소다.
        <p className="mt-3 text-[13px] leading-[1.6] text-brand-faint">
          왼쪽에서 분석할 저장소를 선택하세요.
        </p>
      ) : (
        <ul className="mt-4 grid max-h-[38vh] gap-2 overflow-y-auto">
          {repositories.map((repository) => (
            <SelectedRepositoryCard
              key={repository.githubRepositoryId}
              repository={repository}
              branchName={branchByRepo.get(repository.fullName) ?? ''}
              outcome={outcomes.get(repository.fullName)}
              live={itemByRepository.get(repository.fullName)}
              onBranchChange={onBranchChange}
              onRemove={onRemove}
            />
          ))}
        </ul>
      )}

      {canReset ? (
        <>
          <div className="mt-4 rounded-xl bg-tone-success-bg px-4 py-3 text-[13px] leading-[1.6] font-semibold text-tone-success">
            {progressLabel} · 결과를 확인할 수 있어요.
          </div>
          {/* 고른 저장소를 하나씩 지우지 않고 한 번에 비운다. */}
          <button type="button" onClick={onReset} className={`${PRIMARY_CTA} mt-3`}>
            새로운 분석 요청하기
          </button>
        </>
      ) : allSubmitted ? (
        <div className="mt-4 rounded-xl bg-tone-success-bg px-4 py-3 text-[13px] leading-[1.6] font-semibold text-tone-success">
          분석 {succeeded.length}건을 등록했습니다. 진행 상태는 위 저장소별로 표시됩니다.
        </div>
      ) : (
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className={`${PRIMARY_CTA} mt-4`}
        >
          {isSubmitting
            ? '분석을 등록하는 중입니다…'
            : blockedReason !== null
              ? '다른 분석이 진행 중입니다'
              : repositories.length === 0
                ? '분석할 저장소를 고르세요'
                : isRetry
                  ? `실패한 ${failed.length}개 다시 시도`
                  : `${submittable.length}개 저장소 분석 시작`}
        </button>
      )}

      {/*
        막힌 이유를 말한다. 버튼만 비활성으로 두면 사용자는 무엇이 잘못됐는지 알 수 없다.
        실패한 저장소만 다시 시도하는 것도 이 동안에는 막힌다 -- 묶음에 항목을 더하려면
        구성원 집합을 가변으로 만들어야 하고, 그것은 "한 번에 한 묶음"과 어긋난다.
      */}
      {blockedReason !== null && !canReset && (
        <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-faint">{blockedReason}</p>
      )}

      {/* 상한에 닿아 체크박스가 잠긴 이유. 말하지 않으면 화면이 고장 난 것처럼 보인다. */}
      {selectionNotice !== null && !canReset && (
        <p className="mt-2 text-[12.5px] leading-[1.6] text-tone-caution">{selectionNotice}</p>
      )}

      {/*
        요청 자체가 거절된 경우. 항목별 실패는 응답 본문으로 와 카드가 그리지만, 이쪽은
        예외로만 오므로 여기서 말하지 않으면 버튼을 눌러도 아무 일도 없는 화면이 된다.
      */}
      {submitFailure !== null && !isSubmitting && (
        <p role="alert" className="mt-2 text-[12.5px] leading-[1.6] text-tone-danger">
          {submitFailure}
        </p>
      )}

      {outcomes.size > 0 && !isSubmitting && (
        <div className="mt-3 text-[12.5px] leading-[1.6]">
          {failed.length === 0 ? (
            <p className="text-tone-success">
              {succeeded.length}개 저장소의 분석을 모두 등록했습니다.
            </p>
          ) : succeeded.length === 0 ? (
            <p className="text-tone-danger">{failed.length}개 저장소 모두 등록에 실패했습니다.</p>
          ) : (
            <p className="text-tone-caution">
              {succeeded.length}개 등록, {failed.length}개 실패. 등록된 분석은 그대로 진행됩니다.
            </p>
          )}
          {succeeded.length > 0 && (
            <p className="mt-1 text-brand-faint">
              이 화면을 벗어나도 분석은 계속됩니다. 끝나면 저장소마다 결과로 가는 버튼이 생깁니다.
            </p>
          )}
        </div>
      )}

    </section>
  )
}
