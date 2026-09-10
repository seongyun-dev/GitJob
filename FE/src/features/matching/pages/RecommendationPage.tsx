import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatShell, TableScaffold } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * What-if가 비교하는 축. Final `#whatif`의 `현재 → 확보 시` 구조다.
 * 증감값은 C조 계산 결과라 FE가 만들지 않는다(PROJECT_GUIDE §2).
 */
const WHATIF_COLUMNS = ['공고', '지금 부족한 기술', '이 기술 확보 시', '변화'] as const
const WHATIF_TEMPLATE = '1.6fr 1.2fr 1.2fr 100px'

/**
 * Next Skill · What-if 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#nextskill`(hero → `463 370 370` 3열 → 각주)과
 * `section#whatif`(NEWLY MATCHED). 두 섹션을 한 화면에 세로로 쌓았다.
 *
 * 3열 중 첫 칸이 넓은 것은 Final의 `#1 RECOMMENDED` 강조를 그대로 옮긴 것이다.
 * 순위 자리는 세워 두고 값은 비운다. 추천 조회 API가 develop에 없고 추천·What-if
 * 계산은 C조 몫이라 FE가 재현하지 않는다.
 *
 * What-if의 의미는 "이 기술 Evidence가 특정 조건이 되었다고 가정할 때 매칭되는
 * 공고가 얼마나 늘어나는가"다. 취업 확률 증가가 아니다. Final의 증가량 숫자는
 * demo 값이라 옮기지 않는다.
 */
export function RecommendationPage() {
  return (
    <div>
      <PageHero
        eyebrow="NEXT SKILL · TOP 3"
        title="다음에 무엇을 배우면 가장 많이 달라질까요?"
        description="부족한 기술 중 어떤 것을 채우면 비교 대상 공고가 늘어나는지 보여줍니다. 순위와 근거는 서버가 계산합니다."
      />

      {/*
        순위 3칸. Audit에서 "같은 카드 3개가 반복된다"는 지적을 받은 자리다.
        `gj-trio`가 이미 첫 칸을 넓게 잡으므로(1.25fr 1fr 1fr) 폭은 차이가 나 있었지만,
        내부가 완전히 같은 모양이라 위계가 읽히지 않았다.

        그래서 1순위에만 판단 근거의 축(요구 공고 수 · 현재 Level · 목표 Level)을 껍데기로
        세우고, 2·3순위는 한 줄 상태로 둔다. Final의 `#1 RECOMMENDED` 강조와 같은 의도다.
        기술명과 수치는 어느 칸에도 넣지 않는다.
      */}
      <div className="gj-trio mt-7">
        <DataRegion
          eyebrow="#1 RECOMMENDED"
          title="1순위 후보"
          hint="가장 많은 공고가 요구하면서 현재 근거가 부족한 기술입니다."
        >
          <div className="grid gap-2.5">
            <StatShell label="요구 공고" note="계산 후 표시" />
            <StatShell label="현재 Personal Level" note="분석 후 표시" />
            <StatShell label="목표 Level" note="계산 후 표시" />
          </div>
          <div className="mt-3">
            <StateCard
              kind="PREPARING"
              title="추천 결과 준비 중"
              description="학습 후보와 점수 분해, 요구 근거를 돌려주는 조회 API가 준비되면 이 자리에 표시합니다."
            />
          </div>
        </DataRegion>
        <DataRegion eyebrow="#2" title="2순위 후보">
          <StateCard
            kind="PREPARING"
            title="후순위 후보 자리"
            description="1순위와 같은 기준으로 함께 제시됩니다."
          />
        </DataRegion>
        <DataRegion eyebrow="#3" title="3순위 후보">
          <StateCard
            kind="PREPARING"
            title="후순위 후보 자리"
            description="반대 신호나 데이터 공백이 있으면 그 사실도 함께 표시합니다."
          />
        </DataRegion>
      </div>

      <div className="mt-4">
        <DataRegion
          eyebrow="NEWLY MATCHED"
          title="What-if · 이 기술을 채우면 무엇이 달라질까요"
          hint="특정 기술의 Evidence가 올라갔다고 가정할 때 새로 매칭되는 공고를 보여줍니다."
        >
          <TableScaffold columns={WHATIF_COLUMNS} template={WHATIF_TEMPLATE}>
            <StateCard
              kind="PREPARING"
              title="What-if 결과 준비 중"
              description="서버가 계산해 돌려주면 그대로 표시합니다. 화면에서 증가량을 만들어내지 않습니다."
            />
          </TableScaffold>
        </DataRegion>
      </div>

      <PageFootnote>
        공고 수 변화는 합격 가능성이 아니라, 해당 기술의 Personal Evidence를 목표 수준으로
        올렸을 때 비교 대상에 들어오는 공고가 얼마나 늘어나는지를 뜻합니다.
      </PageFootnote>
    </div>
  )
}
