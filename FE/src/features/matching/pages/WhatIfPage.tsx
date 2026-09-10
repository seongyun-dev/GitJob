import { Link } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * What-if · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `03 What-if`).
 *
 * v2 구조: hero → 후보 순위 칩 → `571 / 757` split(가정 카드 | NEWLY MATCHED) → 각주.
 *
 * What-if의 의미는 **"이 기술 Evidence가 목표 Level이 되었다고 가정할 때 기술요건이
 * 매칭되는 공고가 얼마나 늘어나는가"** 다. 합격 가능성 증가가 아니다.
 *
 * 증감을 화면에서 계산하지 않는다. `현재 12 → 확보 후 27` 같은 값은 C조가 같은
 * Snapshot에서 다시 대조해 돌려주는 결과이고, FE가 `after - before`로 만들어도 되는
 * 값이 아니다(PROJECT_GUIDE §2). 조회 API가 develop에 없다.
 *
 * 192에서는 이 내용을 추천 화면 안에 접어 두었는데, v2가 별도 아트보드로 분리했고
 * 비교 축(현재 / 확보 후)과 새로 매칭되는 공고 목록이 화면 하나를 채울 만큼 크다.
 */
export function WhatIfPage() {
  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 다음 학습 기술
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="NEXT SKILL · WHAT-IF"
          title="이 기술을 목표 Level로 만들면 무엇이 달라질까요?"
          description="공고 매칭과 같은 Snapshot에서, 특정 기술의 Personal Evidence가 목표 Level이 되었다고 가정한 결과입니다."
        />
      </div>

      {/* v2의 `571 / 757`. 왼쪽이 가정, 오른쪽이 그 결과로 새로 매칭되는 공고다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[571px_minmax(0,1fr)]">
        <DataRegion
          eyebrow="#1 RECOMMENDED"
          title="무엇을 가정하나"
          hint="현재 Level에서 목표 Level로 올라갔다고 가정합니다."
        >
          {/* 비교 축. 현재 / 확보 후 두 칸을 세우고 값은 서버가 채운다. */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: '현재', caption: '지금 필수 기술을 모두 충족하는 공고' },
              { label: '확보 후', caption: '목표 Level을 가정했을 때' },
            ].map((item) => (
              <div
                key={item.label}
                className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
              >
                <p className="text-[12px] text-brand-faint">{item.label}</p>
                <p className="mt-1.5 text-[15px] font-[750] text-brand-faint">계산 후 표시</p>
                <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">{item.caption}</p>
              </div>
            ))}
          </div>
          <div className="mt-3">
            <StateCard
              kind="PREPARING"
              title="What-if 결과 준비 중"
              description="서버가 같은 Snapshot에서 다시 대조해 돌려주면 그대로 표시합니다. 화면에서 증가량을 만들어내지 않습니다."
            />
          </div>
        </DataRegion>

        <DataRegion
          eyebrow="NEWLY MATCHED"
          title="새로 기술요건을 충족하는 공고"
          hint="가정이 성립했을 때 비교 대상에 새로 들어오는 공고입니다."
        >
          <StateCard
            kind="PREPARING"
            title="새로 매칭되는 공고 준비 중"
            description="어떤 공고가 새로 충족되는지, 그 공고가 어떤 기술을 요구하는지 함께 표시합니다."
          />
        </DataRegion>
      </div>

      <PageFootnote>
        공고 수 변화는 합격 가능성이 아니라, 해당 기술의 Personal Evidence를 목표 수준으로
        올렸을 때 기술요건이 매칭되는 공고가 얼마나 늘어나는지를 뜻합니다.
      </PageFootnote>
    </div>
  )
}
