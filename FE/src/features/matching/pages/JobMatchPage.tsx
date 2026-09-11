import { Link } from 'react-router'
import { JobFilterRail } from '@/features/matching/components/JobFilterRail'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 공고 매칭 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `02 Job Match`).
 *
 * v2 구조: hero(+공고 Snapshot) → 필터 레일 `260 / 1082` → 지표 3연(실측 `332.7 x 3`)
 * → `956/372` split(공고별 기술요건 대조 | 요약 패널) → 각주.
 *
 * 공고와 충족 분포를 표시하지 않는다. 매칭 조회 API가 develop에 없다. v2의 `87건`,
 * `12 100% 충족`, 개별 공고명은 전부 demo 값이라 옮기지 않는다.
 *
 * 필터 컨트롤은 비활성이다(`JobFilterRail`). 축과 선택지 이름은 제품 정의라 보여주고
 * 동작만 막는다. 눌리는데 아무 일도 없는 컨트롤을 만들지 않는다.
 *
 * 기술요건 충족만 보여준다. 합격 가능성이나 지원 가능 여부를 판정하지 않는다.
 */
const MATCH_STATS = [
  { label: '대조한 공고', note: '대조 후 표시', caption: '선택한 직무의 수집된 공고 전체' },
  { label: '필수 100% 충족', note: '대조 후 표시', caption: '모든 필수 기술 보유' },
  { label: '기술 1개 부족', note: '대조 후 표시', caption: '하나만 더 채우면 되는 구간' },
] as const

export function JobMatchPage() {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="JOB MATCH"
          title="공고 요구 기술과 비교했어요"
          description="기술요건 충족 여부만 보여줍니다. 합격 가능성이나 지원 가능 여부는 판정하지 않습니다."
        />
        <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
          <p className="text-[12px] text-brand-faint">공고 Snapshot</p>
          <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">수집 기준 미정</p>
        </div>
      </div>

      {/* v2의 `260 / 1082` 레일 배치. 좁은 화면에서는 레일이 위로 접힌다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <JobFilterRail />

        <div className="grid gap-4">
          <StatStrip items={MATCH_STATS} />

          <div className="gj-split">
            <DataRegion
              eyebrow="POSTINGS"
              title="공고별 기술요건 대조"
              hint="✓ 보유 · △ Level 부족 · ✕ Evidence 없음 순으로 공고마다 나란히 표시됩니다."
            >
              <StateCard
                kind="EMPTY"
                title="비교할 Evidence가 아직 없어요"
                description="Repository 분석을 마치고 직무를 선택하면 그 결과로 공고 요구 기술과 비교합니다."
                action={
                  <Link
                    to="/onboarding/repositories"
                    className="inline-block rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                  >
                    저장소 선택으로
                  </Link>
                }
              />
            </DataRegion>

            <div className="grid gap-4">
              <DataRegion
                eyebrow="HOW"
                title="무엇을 비교하나요"
                hint="공고가 적은 요구 기술을 내 Evidence와 기술 단위로 대조합니다."
              >
                <dl className="grid gap-3">
                  {[
                    { t: '필수 기술', d: '공고가 반드시 요구하는 기술의 충족 여부' },
                    { t: '우대 기술', d: '있으면 좋은 기술의 충족 여부' },
                    { t: '부족 기술', d: '아직 근거가 없어 다음 학습 후보가 되는 기술' },
                  ].map((item) => (
                    <div key={item.t}>
                      <dt className="text-[13px] font-semibold text-brand-ink">{item.t}</dt>
                      <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                        {item.d}
                      </dd>
                    </div>
                  ))}
                </dl>
                <Link
                  to="/skill-gap"
                  className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
                >
                  부족한 기술 자세히 보기
                </Link>
                {/* v2는 Gap 보기 바로 아래에 추천 화면 이동을 주 버튼으로 둔다. */}
                <Link
                  to="/recommendations"
                  className="mt-2.5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
                >
                  다음 기술 추천 보기
                </Link>
              </DataRegion>
            </div>
          </div>
        </div>
      </div>

      <PageFootnote>
        기술요건 충족도만 보여줍니다. 합격 가능성이나 취업 확률은 계산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
