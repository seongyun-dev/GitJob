import type { MonitoringOverview } from '@/features/admin/monitoring/api/monitoringApi'
import type { CoverageState } from '@/features/admin/monitoring/model/monitoringState'
import { Pill } from '@/shared/ui/Pill'

/**
 * Data Platform · 티켓 S15P21E102-210.
 *
 * 이 섹션의 요점은 **"서비스가 준비되지 않음"과 "상세 지표가 아직 연결되지 않음"을
 * 구분해 보여주는 것**이다. HDFS·Spark·Collector는 실제로 돌고 있다. 돌지 않는 것은
 * 그것들의 지표 수집이다. 그래서 카드는 서비스가 죽었다고 말하지 않고, 무엇이 연결되면
 * 무엇이 보일지를 말한다.
 *
 * 상태는 `overview.coverage`가 준다(BE 계약, 티켓 209). 화면이 판단하지 않는다. exporter가
 * 붙어 `COLLECTED`가 오면 카드가 바뀌고, 그때 수치를 채우는 것은 후속 티켓이다.
 *
 * 숫자 자리에 `N/A`를 두고 값을 만들지 않는다. 확정 디자인도 같은 표기이며, 그 자리에
 * 0이나 그럴듯한 수치를 넣으면 운영자는 파이프라인이 동작한다고 읽는다.
 */

/**
 * 카드에 적을 내용.
 *
 * 제품 정의이지 관측값이 아니다 — 그래서 API가 없어도 그릴 수 있다. `prerequisite`는
 * S15P21E102-205 문서 3장이 후속 작업으로 지목한 것과 같다.
 */
const PLATFORMS: readonly {
  key: keyof MonitoringOverview['coverage']
  name: string
  prerequisite: string
  willShow: string
}[] = [
  {
    key: 'hdfs',
    name: 'HDFS',
    prerequisite: 'NameNode JMX exporter 연결 후',
    willShow: '용량 · Block · DataNode 상태',
  },
  {
    key: 'spark',
    name: 'Spark',
    prerequisite: 'Metrics Sink 연결 후',
    willShow: 'Application · Executor · 실패율',
  },
  {
    key: 'collector',
    name: 'Collector',
    prerequisite: 'Exporter 연결 후',
    willShow: '수집 건수 · 지연 · 오류율',
  },
  {
    key: 'kafkaBusiness',
    name: 'Kafka Topic',
    prerequisite: 'topic 지표 연동 후',
    willShow: '처리량 · Consumer lag',
  },
]

function CoverageBadge({ state }: { state: CoverageState }) {
  if (state === 'COLLECTED') {
    return <Pill tone="success">COLLECTED</Pill>
  }
  return <Pill tone="neutral">PREPARING</Pill>
}

export function DataPlatformCards({
  coverage,
}: {
  coverage: MonitoringOverview['coverage']
}) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 px-1">
        <h2 className="text-[18px] font-[750] tracking-[-0.03em] text-brand-ink">
          Data Platform
        </h2>
        <span className="text-[12.5px] text-brand-faint">
          서비스는 동작 중 · 상세 지표 수집 전
        </span>
      </div>

      <div className="gj-cards">
        {PLATFORMS.map((platform) => {
          const state = coverage[platform.key]
          return (
            <div
              key={platform.key}
              className="rounded-[18px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
            >
              <div className="flex items-center justify-between gap-2.5">
                <span className="text-[14px] font-[750] text-brand-ink">{platform.name}</span>
                <CoverageBadge state={state} />
              </div>

              {/* 수치 자리. 점선 테두리가 "아직 들어오지 않았다"를 말한다. */}
              <div className="mt-3.5 rounded-[12px] border border-dashed border-brand-box px-4 py-4 text-center">
                <div className="inline-flex gap-1">
                  {[0, 1, 2].map((index) => (
                    <span key={index} className="h-1.5 w-4.5 rounded-sm bg-[#E4E9F1]" />
                  ))}
                </div>
                <p className="mt-2 text-[22px] font-extrabold tracking-[-0.04em] text-brand-faint">
                  N/A
                </p>
              </div>

              <p className="mt-3 text-[12px] leading-[1.55] text-brand-faint">
                <b className="font-bold text-brand-muted">{platform.prerequisite}</b>
                <br />
                {platform.willShow}
              </p>
            </div>
          )
        })}
      </div>

      <p className="mt-3 px-1.5 text-[12px] leading-[1.6] text-brand-faint">
        PREPARING은 수집 파이프라인이 연결되지 않은 상태입니다. 서비스가 중단된 것이
        아니며, 컨테이너와 서버의 동작 여부는 Infrastructure Map에서 확인합니다. 수집이
        시작된 뒤 값이 비어 있는 경우(NO_DATA)나 수집 오류(FAILED)와도 구분해 표시합니다.
      </p>
    </section>
  )
}
