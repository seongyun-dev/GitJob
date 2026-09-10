import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatShell } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Technology Detail · Project Guide 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#techdetail` — hero → `610 610` 2등분(공고 GAP | 현재 비교)
 * → EVIDENCE GOAL 영역. 판정 기준을 별도 영역으로 떼어 놓은 구성을 그대로 가져왔다.
 *
 * 공고 GAP 수치·Roadmap·학습 프로젝트를 표시하지 않는다. 관련 조회 API가 develop에
 * 없고, 학습 자료를 FE가 지어내면 근거 없는 내용이 된다.
 */
export function TechnologyDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <PageHero
        eyebrow="RECOMMENDED TECHNOLOGY"
        title={techId ?? '기술 상세'}
        description="이 기술을 왜 추천했는지, 어떤 순서로 익히고 무엇을 만들어 Evidence를 남길 수 있는지 안내합니다."
      />

      {/*
        Final `#techdetail`은 hero 아래에 `Personal L1 / Target L2 / What-if +15`
        세 축을 먼저 보여준다. 축 이름은 정의이고 값은 계산 결과라 비운다.
      */}
      <div className="gj-stats mt-7">
        <StatShell label="요구 공고" note="대조 후 표시" caption="이 기술을 필수로 요구하는 공고" />
        <StatShell label="현재 Personal Level" note="분석 후 표시" caption="본인 Commit 기준" />
        <StatShell label="목표 Level" note="계산 후 표시" caption="다음 판정 단계" />
      </div>

      <div className="gj-duo mt-4">
        <DataRegion
          eyebrow="JOB GAP"
          title="공고 요구 현황"
          hint="이 기술을 필수로 요구하는 공고가 얼마나 되는지 표시됩니다."
        >
          <StateCard
            kind="PREPARING"
            title="공고 요구 현황 준비 중"
            description="공고 대조 결과를 돌려주는 조회 API가 준비되면 이 자리에 표시합니다."
          />
        </DataRegion>

        <DataRegion
          eyebrow="MY EVIDENCE"
          title="현재 내 근거"
          hint="이 기술에 대해 현재 확인된 Evidence와 부족한 근거가 표시됩니다."
        >
          <StateCard
            kind="PREPARING"
            title="판정 결과 준비 중"
            description="Evidence 조회 API가 준비되면 현재 Level과 미충족 규칙을 함께 보여줍니다."
          />
        </DataRegion>
      </div>

      <div className="mt-4">
        <DataRegion
          eyebrow="EVIDENCE GOAL"
          title="다음 Level 판정 기준"
          hint="어떤 근거를 남기면 다음 Level로 판정되는지 규칙 그대로 보여줍니다."
        >
          <StateCard
            kind="PREPARING"
            title="판정 기준 준비 중"
            description="규칙과 학습 순서, 만들어 볼 프로젝트를 돌려주는 조회 API가 준비되면 여기에 표시합니다."
          />
        </DataRegion>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          to={techId === undefined ? '/trends' : `/trends/${techId}`}
          className="rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink shadow-[0_10px_28px_rgba(25,47,81,0.07)] hover:border-brand-line-active"
        >
          이 기술의 트렌드 보기
        </Link>
        <Link
          to="/recommendations"
          className="rounded-xl px-4 py-2.5 text-[13px] text-brand-muted hover:text-brand-ink"
        >
          다른 후보 보기
        </Link>
      </div>

      <PageFootnote>
        Level은 숙련도가 아니라 근거의 누적 상태입니다. 학습 안내는 근거를 남기는 방법을
        보여주는 것이고 점수를 올리는 방법이 아닙니다.
      </PageFootnote>
    </div>
  )
}
