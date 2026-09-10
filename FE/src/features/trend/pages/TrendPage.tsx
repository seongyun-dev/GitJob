import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { ListShell, SourceLegend, TableScaffold } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Final `#trend`가 비교하는 세 출처. 탭이 아니라 정적 범례로 둔다.
 * 전환할 데이터가 없는 상태에서 탭을 만들면 눌러도 아무 일이 없는 컨트롤이 된다.
 */
const TREND_SOURCES = ['채용공고', 'GitHub', 'Stack Overflow'] as const

/** Final `#trend` 순위 표의 컬럼. 단위는 출처마다 달라 헤더에서 중립적으로 적는다. */
const TREND_COLUMNS = ['#', '기술', '출처 내 비중', '전기 대비'] as const
const TREND_TEMPLATE = '48px 1.4fr .9fr .9fr'

/**
 * Technology Trend 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#trend` — hero → `846 372` split(기술 순위 표 | 우측 패널).
 * 카드 세 장을 나열하는 구성이 아니었다.
 *
 * 순위·비중·증감을 표시하지 않는다. 트렌드 조회 API가 develop에 없고, 공고 집계와
 * 기술 popularity 계산은 FE가 하지 않는다.
 *
 * 출처(채용공고 · GitHub · Stack Overflow)를 하나로 합치지 않는다는 설계 규칙에 따라
 * 우측 패널에서 출처별 상태를 각각 밝힌다. 한 출처가 없다고 다른 출처를 가리지 않는다.
 */
export function TrendPage() {
  return (
    <div>
      <PageHero
        eyebrow="TECHNOLOGY TREND"
        title="기술 트렌드"
        description="출처별로만 비교합니다. 채용공고와 GitHub 등 출처가 다른 수치는 하나로 합치지 않고 각각 보여줍니다."
      />

      <div className="gj-split mt-7">
        <DataRegion
          eyebrow="RANKING"
          title="기술 순위"
          hint="출처를 하나씩만 비교합니다. 서로 다른 출처의 수치를 합산하거나 종합 점수로 만들지 않습니다."
        >
          {/*
            출처 구분. Final은 탭이지만 여기서는 읽기 전용 범례다. 전환할 데이터가 없어
            탭으로 만들면 누를 수 있는데 아무 일도 일어나지 않는 컨트롤이 된다.
            데이터가 붙는 티켓에서 이 자리를 탭으로 승격한다.
          */}
          <SourceLegend sources={TREND_SOURCES} />
          <div className="mt-3">
            <TableScaffold columns={TREND_COLUMNS} template={TREND_TEMPLATE}>
              <StateCard
                kind="PREPARING"
                title="순위를 아직 불러올 수 없어요"
                description="집계 결과를 돌려주는 조회 API가 준비되면 이 표에 채워집니다. 화면에서 집계하지 않습니다."
              />
            </TableScaffold>
          </div>
        </DataRegion>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">SOURCES</p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            출처별 상태
          </h2>
          <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-muted">
            출처마다 단위와 기간이 달라 따로 표시합니다.
          </p>
          <div className="mt-4 grid gap-2.5">
            {TREND_SOURCES.map((source) => (
              <ListShell
                key={source}
                name={source}
                description="단위와 기간이 달라 이 출처 안에서만 비교합니다."
                status="PREPARING"
              />
            ))}
          </div>
        </aside>
      </div>

      <PageFootnote>
        종합 Trend 점수는 제공하지 않습니다. 출처마다 준비 상태가 다르며 데이터가 없는 것은
        오류가 아닙니다.
      </PageFootnote>
    </div>
  )
}
