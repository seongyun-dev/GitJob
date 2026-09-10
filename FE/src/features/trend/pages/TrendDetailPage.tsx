import { Link, useParams } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 트렌드 상세 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `13 Trend Detail`).
 *
 * v2 구조: 개요 복귀 링크 → hero → `737.8 / 590.2` split(시계열 | 보조) → 각주.
 *
 * v2는 `POSTING COUNT` / `POSTING SHARE` 지표 토글과 출처 탭을 둔다. 전환할 데이터가
 * 없어 **토글을 만들지 않는다.** 누를 수 있는데 아무 일도 없는 컨트롤을 만들지 않기
 * 위해, 지표 축 이름만 정적으로 밝히고 값 자리는 비운다.
 *
 * 두 출처의 Y축 · 단위 · 기간은 각각 독립이다. 한 화면에 겹쳐 그리거나 합산하지 않는다.
 */
const AXES = [
  { label: '공고 건수', hint: '해당 기간에 이 기술을 언급한 공고 수' },
  { label: '언급 비중', hint: '같은 기간 전체 공고 대비 비율' },
] as const

export function TrendDetailPage() {
  const { techId } = useParams()

  return (
    <div>
      <Link
        to="/trends"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 트렌드 개요
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="TREND DETAIL"
          title="이 기술의 출처별 추이"
          description="두 출처의 Y축 · 단위 · 기간은 각각 독립적입니다. 서로 비교하거나 합산하지 마세요."
        />
      </div>

      {/* v2의 `737.8 / 590.2`. 왼쪽이 시계열, 오른쪽이 출처별 상태다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,737fr)_minmax(0,590fr)]">
        <DataRegion
          eyebrow="JOB · 채용공고"
          title="기간별 추이"
          hint="공고 건수와 언급 비중을 같은 기간 축에서 봅니다."
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {AXES.map((axis) => (
              <div
                key={axis.label}
                className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
              >
                <p className="text-[12px] text-brand-faint">{axis.label}</p>
                <p className="mt-1.5 text-[15px] font-[750] text-brand-faint">집계 후 표시</p>
                <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">{axis.hint}</p>
              </div>
            ))}
          </div>
          <div className="mt-3">
            <StateCard
              kind="PREPARING"
              title="추이를 아직 불러올 수 없어요"
              description="기간별 집계가 준비되면 이 영역에 표시합니다. 화면에서 추세를 만들어내지 않습니다."
            />
          </div>
        </DataRegion>

        <DataRegion
          eyebrow="OTHER SOURCES"
          title="다른 출처의 상태"
          hint="출처마다 지원 범위와 기간이 달라 따로 표시합니다."
        >
          <StateCard
            kind="NO_DATA"
            title="이 출처에는 아직 데이터가 없어요"
            description="수집된 항목이 없는 것은 오류가 아닙니다. 지원하지 않는 출처는 그 사실을 그대로 표시합니다."
          />
        </DataRegion>
      </div>

      <PageFootnote>
        종합 Trend 점수는 제공하지 않습니다. 출처마다 준비 상태가 다르며 데이터가 없는 것은
        오류가 아닙니다.
        {techId !== undefined && (
          <>
            {' · '}
            기술 <span className="font-evidence text-brand-muted">{techId}</span>
          </>
        )}
      </PageFootnote>
    </div>
  )
}
