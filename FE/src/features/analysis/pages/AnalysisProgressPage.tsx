import { Link, useParams } from 'react-router'
import { AnalysisStepList } from '@/features/analysis/components/AnalysisStepList'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 분석 진행 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `07 Analysis Progress`).
 *
 * v2 구조: hero → 진행 영역(단계 4칸) + 우측 `PARTIAL RESULT` 패널(958/372).
 * 단계 목록은 `AnalysisStepList`로 옮겨 이 페이지는 배치만 맡는다.
 *
 * 진행률과 중간 결과를 표시하지 않는다. 상태 조회 API가 develop에 없어
 * (S15P21E102-133 진행 중) 단계·처리 건수·남은 시간을 알 방법이 없다. v2의 `72%`,
 * `약 1분 남음`, 우측 패널의 `Java L3` 같은 중간 결과는 전부 demo 값이다.
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
            <StateCard
              kind="PREPARING"
              title="진행 상태를 아직 조회할 수 없어요"
              description="단계별 진행과 처리 대상 수를 돌려주는 조회 API가 준비되면 위 단계에 표시됩니다. 접수된 분석은 서버에서 계속 진행됩니다."
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
