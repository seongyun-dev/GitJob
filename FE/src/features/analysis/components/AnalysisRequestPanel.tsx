import type { AnalysisRequestOutcome, RepositorySummary } from '@/features/analysis/api/types'
import { SelectedRepositoryCard } from '@/features/analysis/components/SelectedRepositoryCard'

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
 * 성공 후 라우팅하지 않는 이유: 진행 상태 화면(S15P21E102-136)과 그 화면이 쓸
 * `GET /analyses/{analysisId}`(S15P21E102-133)이 둘 다 없다. 응답의 `statusUrl`은
 * 아직 열리지 않은 경로를 가리키므로 링크로 쓰지 않고, 받은 `analysisId`를
 * 저장소별로 보여준 뒤 멈춘다.
 */

/** Final CTA의 그라디언트·그림자 값. */
const PRIMARY_CTA =
  'w-full rounded-xl bg-[linear-gradient(135deg,var(--color-brand-600),var(--color-brand-400))] px-[22px] py-[14px] text-[14px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)] transition-shadow not-disabled:hover:shadow-[0_16px_32px_rgba(47,94,235,0.34)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none'

/**
 * 분석이 무엇을 근거로 삼는지에 대한 설명. Final 패널의 01/02/03 문구를 그대로 썼다.
 *
 * 지어낸 문구가 아니고, 우리 계약과도 맞는다. C조 Evidence 계약의
 * `EvidenceProof.kind` 3종(`DIRECT_DEPENDENCY` · `IMPLEMENTATION` · `PARTICIPATION`)에
 * 1:1로 대응한다(`AI/recommendation/evidence.py`).
 */
const EVIDENCE_STEPS: ReadonlyArray<{ step: string; text: string }> = [
  { step: '01', text: '빌드 · 설정 파일에서 Dependency 확인' },
  { step: '02', text: '소스 코드에서 실제 설정 · 구현 사용 판정' },
  { step: '03', text: 'Commit 작성자로 본인 기여 여부 확인' },
]

export function AnalysisRequestPanel({
  repositories,
  branchByRepo,
  outcomes,
  isSubmitting,
  onBranchChange,
  onRemove,
  onSubmit,
}: {
  repositories: RepositorySummary[]
  branchByRepo: Map<string, string>
  outcomes: Map<string, AnalysisRequestOutcome>
  isSubmitting: boolean
  onBranchChange: (fullName: string, branch: string) => void
  onRemove: (fullName: string) => void
  onSubmit: () => void
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
  const canSubmit = submittable.length > 0 && branchesReady && !isSubmitting

  return (
    <section
      aria-labelledby="analysis-request-heading"
      className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:sticky lg:top-[96px]"
    >
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">ANALYSIS SCOPE</p>
      <h2
        id="analysis-request-heading"
        className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink"
      >
        선택한 Repository {repositories.length}개
      </h2>

      {repositories.length === 0 ? (
        // 패널은 항상 자리를 지킨다. Final에서도 ANALYSIS SCOPE 블록이 화면의 고정 요소다.
        <p className="mt-3 text-[13px] leading-[1.6] text-brand-faint">
          왼쪽 목록에서 분석할 Repository를 고르세요. 여러 개를 함께 고를 수 있습니다.
        </p>
      ) : (
        <ul className="mt-4 grid max-h-[38vh] gap-2 overflow-y-auto">
          {repositories.map((repository) => (
            <SelectedRepositoryCard
              key={repository.githubRepositoryId}
              repository={repository}
              branchName={branchByRepo.get(repository.fullName) ?? ''}
              outcome={outcomes.get(repository.fullName)}
              onBranchChange={onBranchChange}
              onRemove={onRemove}
            />
          ))}
        </ul>
      )}

      <dl className="mt-4 border-t border-brand-line pt-1">
        {EVIDENCE_STEPS.map((item) => (
          <div key={item.step} className="flex gap-3 py-3">
            <dt className="shrink-0 text-[11px] leading-[1.5] font-extrabold text-brand-400">
              {item.step}
            </dt>
            <dd className="min-w-0 text-[13.5px] leading-[1.5] text-brand-body">{item.text}</dd>
          </div>
        ))}
      </dl>

      <button type="button" onClick={onSubmit} disabled={!canSubmit} className={PRIMARY_CTA}>
        {isSubmitting
          ? '분석을 등록하는 중입니다…'
          : submittable.length === 0
            ? // 고른 저장소가 모두 접수된 상태. "0개 분석 시작"으로 읽히지 않게 문구를 바꾼다.
              '모두 등록되었습니다'
            : isRetry
              ? `실패한 ${failed.length}개 다시 시도`
              : `${submittable.length}개 Repository 분석 시작`}
      </button>

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
              진행 상태 화면은 아직 제공되지 않습니다. 저장소별 분석 ID를 보관해 주세요.
            </p>
          )}
        </div>
      )}

      <p className="mt-3 text-[12.5px] leading-[1.6] text-brand-faint">
        분석 결과는 Evidence(파일 · 설정 · Commit)로 제시되며 점수로 환산하지 않습니다.
      </p>
    </section>
  )
}
