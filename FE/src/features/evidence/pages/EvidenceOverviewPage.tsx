import { Link } from 'react-router'
import {
  AnalysisContextPanel,
  ReinforcementPanel,
} from '@/features/evidence/components/EvidenceSidePanels'
import { EvidenceTable } from '@/features/evidence/components/EvidenceTable'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { LevelLegend } from '@/shared/ui/LevelBadge'
import { StatStrip } from '@/shared/ui/StatStrip'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 기술 Evidence 결과 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `08 My Evidence`).
 *
 * v2 구조: hero(+우측 CTA 2개) → 지표 4연 스트립 → `956/372` split
 * (기술별 판정 표 | 근거 보강 필요 + ANALYSIS CONTEXT) → 각주.
 *
 * 기술 목록과 Level을 표시하지 않는다. Evidence 결과 목록 API가 develop에 없고
 * (S15P21E102-134 미착수) Evidence 관련 Controller·DTO·Entity도 하나도 없다.
 * Level 판정은 C조 몫이라 FE가 계산하지 않는다.
 *
 * v2 hero 우측의 `분석 완료 | 분석 전` 세그먼트는 아트보드에서 상태를 바꿔 보기
 * 위한 디자인 도구 장치라 옮기지 않는다. 그 옆 CTA 두 개는 실제 이동이라 남긴다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-137(이윤서)에 있다. 시각 적용까지만 한다.
 */

/**
 * v2가 hero 아래에 두는 네 지표. 이름과 기준은 제품 정의라 지금 보여줄 수 있고,
 * 값은 Evidence 결과 목록 API가 준다(S15P21E102-134 미착수).
 */
const EVIDENCE_STATS = [
  { label: '확인된 기술', note: '분석 후 표시', caption: 'Personal Evidence 기준' },
  { label: 'Personal L2 이상', note: '분석 후 표시', caption: '본인 Commit으로 확인된 범위' },
  { label: '근거 보강 필요', note: '분석 후 표시', caption: 'Repository Level보다 낮음' },
  { label: '선언만 확인 · L0', note: '분석 후 표시', caption: '의존성 선언 · 사용 코드 없음' },
] as const
export function EvidenceOverviewPage() {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="MY EVIDENCE"
          title="내 GitHub에서 확인된 기술"
          description="Evidence는 점수가 아니라 근거입니다. Personal은 본인 Commit으로 확인된 범위, Repository는 저장소 전체 기준입니다."
        />
        <div className="flex shrink-0 flex-wrap gap-2.5">
          <Link
            to="/onboarding/repositories"
            className="rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            GitHub 다시 분석
          </Link>
          <Link
            to="/roles"
            className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            직무 선택하고 공고 비교
          </Link>
        </div>
      </div>

      <div className="mt-7">
        <StatStrip items={EVIDENCE_STATS} />
      </div>

      <div className="gj-split mt-4">
        <EvidenceTable>
          <StateCard
            kind="PREPARING"
            title="판정 결과를 아직 불러올 수 없어요"
            description="기술별 판정을 돌려주는 조회 API가 준비되면 이 표에 채워집니다. 추정값으로 채우지 않습니다."
          />
        </EvidenceTable>

        <div className="grid gap-4">
          <ReinforcementPanel />
          <AnalysisContextPanel />
        </div>
      </div>

      {/*
        Level 범례. 척도가 네 단계라는 것은 제품 정의라 판정 결과가 없어도 보여준다.
        단계별 의미는 등급 정책 확정 후 constants에서 채워진다.
      */}
      <div className="mt-5">
        <LevelLegend />
      </div>

      <PageFootnote>
        Personal Level이 Repository Level보다 낮은 기술은 저장소에는 구현이 있으나 본인 기여
        근거가 확인되지 않은 경우입니다. 점수로 환산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
