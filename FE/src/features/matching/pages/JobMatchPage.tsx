import { Link } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatShell } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Job Match · Skill Gap 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#jobmatch` — hero → 필터 바 → 지표 행 → `846 372` split.
 *
 * 필터 바는 만들지 않았다. 공고 조회 API가 없어 동작하지 않는 컨트롤이 되고,
 * 지역·경력 선택지는 실제 계약에서 온 값이 아니다.
 *
 * 공고 수·충족률·부족 기술도 표시하지 않는다. 관련 조회 API가 develop에 없다
 * (`shared/api/queryKeys`의 `matching` 계열이 전부 BE 미구현).
 *
 * 이 화면은 기술요건 충족도만 다룬다. 합격 확률·취업 가능성은 이 제품이 만들지 않는다.
 */
export function JobMatchPage() {
  return (
    <div>
      <PageHero
        eyebrow="JOB MATCH"
        title="공고 요구 기술과 비교했어요"
        description="채용공고가 요구하는 기술과 현재 확인된 Evidence를 비교합니다. 기술요건이 얼마나 충족되는지만 보여줍니다."
      />

      {/*
        Final `#jobmatch`는 hero 아래에 비교 기준(공고 Snapshot · 전체 공고 · 내 조건)을
        먼저 세운다. 값은 조회 API가 있어야 알 수 있고, 축은 지금 세울 수 있다.
      */}
      <div className="gj-stats mt-7">
        <StatShell label="비교한 공고" note="대조 후 표시" caption="수집된 공고 전체 기준" />
        <StatShell label="필수 100% 충족" note="대조 후 표시" caption="현재 Evidence 기준" />
        <StatShell label="부족한 기술" note="대조 후 표시" caption="다음 학습 후보" />
        <StatShell label="공고 Snapshot" note="수집 기준 미정" caption="수집 시점이 표시됩니다" />
      </div>

      <div className="mt-4 grid gap-4">
        <DataRegion
          eyebrow="SUMMARY"
          title="대조 결과 요약"
          hint="대조한 공고 수와 필수 기술 충족 현황이 이 자리에 들어갑니다."
        >
          <StateCard
            kind="PREPARING"
            title="요약 지표를 아직 계산할 수 없어요"
            description="목표 직무의 요구 기술과 Evidence를 비교하는 조회 API가 준비되면 여기에 표시합니다."
          />
        </DataRegion>

        <div className="gj-split">
          <DataRegion
            eyebrow="POSTINGS"
            title="공고별 기술 요건 대조"
            hint="공고마다 어떤 기술이 충족되고 무엇이 부족한지 나란히 보여줍니다."
          >
            <StateCard
              kind="EMPTY"
              title="비교할 Evidence가 아직 없어요"
              description="Repository 분석을 먼저 완료하면 그 결과로 공고 요구 기술과 비교합니다."
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

          <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">HOW</p>
            <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
              무엇을 비교하나요
            </h2>
            <dl className="mt-4 grid gap-3">
              <div>
                <dt className="text-[13px] font-semibold text-brand-ink">필수 기술</dt>
                <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  공고가 반드시 요구하는 기술의 충족 여부
                </dd>
              </div>
              <div>
                <dt className="text-[13px] font-semibold text-brand-ink">우대 기술</dt>
                <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  있으면 좋은 기술의 충족 여부
                </dd>
              </div>
              <div>
                <dt className="text-[13px] font-semibold text-brand-ink">부족 기술</dt>
                <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">
                  아직 근거가 없어 다음 학습 후보가 되는 기술
                </dd>
              </div>
            </dl>
            <Link
              to="/recommendations"
              className="mt-4 block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              다음 학습 기술 보기
            </Link>
          </aside>
        </div>
      </div>

      <PageFootnote>
        기술요건 충족도만 보여줍니다. 합격 가능성이나 취업 확률은 계산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
