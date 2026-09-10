import { StateCard } from '@/shared/ui/StateCard'
import { TableScaffold } from '@/shared/ui/Scaffold'

/**
 * Recent Events · 티켓 S15P21E102-210.
 *
 * **값이 하나도 없다.** 상태 변화 이력을 주는 공급원이 없다 — Alertmanager는 도입되지
 * 않았고(S15P21E102-187의 후속), BE `overview` 응답에도 이벤트 필드가 없다.
 *
 * 확정 디자인의 다섯 줄("모든 Prometheus target 정상", "Spark Worker heartbeat 수신" 등)은
 * 디자인 파일 스스로 `DESIGN MOCK DATA ONLY`라고 적어 둔 mock이다. 그대로 옮기면 화면이
 * 일어나지 않은 사건을 주장하고, 그 거짓은 운영 화면에서 가장 나쁜 종류다.
 *
 * 대신 표의 골격은 남긴다. 컬럼 이름은 제품이 무엇을 보여줄지에 대한 정의이지 사용자
 * 데이터가 아니므로 API 없이도 그릴 수 있고, 그려야 무엇이 들어올 자리인지 전달된다
 * (`shared/ui/Scaffold`의 판단을 따른다).
 */

/** 확정 디자인 Recent Events의 4열. `52px 14px 1fr auto`를 반응형으로 옮겼다. */
const COLUMNS = ['TIME', 'SEVERITY', 'MESSAGE', 'SOURCE'] as const
const TEMPLATE = '64px 72px minmax(0, 1fr) 120px'

export function RecentEvents() {
  return (
    <div className="rounded-[18px] border border-brand-line bg-white px-6 py-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            RECENT EVENTS
          </p>
          <h3 className="mt-1.5 text-[13px] font-[750] text-brand-ink">최근 상태 변화</h3>
        </div>
        <span className="text-[12px] text-brand-faint">Alertmanager 연결 후 표시</span>
      </div>

      <div className="mt-3">
        <TableScaffold columns={COLUMNS} template={TEMPLATE}>
          <StateCard
            kind="PREPARING"
            title="상태 변화 이력이 아직 없습니다"
            description="이벤트를 주는 공급원이 연결되지 않았습니다. Alertmanager를 도입하면 target 상태 변화와 임계치 초과가 이 표에 쌓입니다. 지금 서버 상태는 위 Infrastructure Map에서 확인할 수 있습니다."
          />
        </TableScaffold>
      </div>
    </div>
  )
}
