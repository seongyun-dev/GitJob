/**
 * Recent Events · 티켓 S15P21E102-210, 표현 축소 S15P21E102-313.
 *
 * **값이 하나도 없다.** 상태 변화 이력을 주는 공급원이 없다. 2026-09-18 확인 결과
 * Alertmanager 컨테이너·Prometheus alert rule·이벤트 조회 API·이벤트 저장 테이블이 모두
 * 없고, 연동 예정으로 열려 있는 이슈도 없다(S15P21E102-187은 완료됐고 그 산출물은
 * Prometheus·Grafana·node-exporter다).
 *
 * 확정 디자인의 다섯 줄("모든 Prometheus target 정상" 등)은 디자인 파일 스스로
 * `DESIGN MOCK DATA ONLY`라고 적어 둔 mock이다. 그대로 옮기면 화면이 일어나지 않은
 * 사건을 주장하고, 그 거짓은 운영 화면에서 가장 나쁜 종류다.
 *
 * <h2>왜 표 골격까지 걷어냈나</h2>
 *
 * 이전 판은 `TIME · SEVERITY · MESSAGE · SOURCE` 4열 헤더와 `PREPARING` 상태 카드를 두어
 * "무엇이 들어올 자리인지" 보이려 했다. 그런데 그 크기가 옆의 Disk Capacity와 같아서,
 * 값이 하나도 없는 영역이 실제 지표 카드와 같은 무게로 읽혔다. 공급원이 예정돼 있다면
 * 자리를 잡아 두는 것이 맞지만 그렇지도 않으므로, 없는 기능을 곧 올 기능처럼 크게
 * 보여 주는 쪽이 된다.
 *
 * 그래서 한 줄 안내로 줄인다. 운영자에게 필요한 정보는 "여기서는 볼 수 없다"와 "그럼
 * 어디서 보나" 두 가지뿐이고, 둘 다 한 문장이면 된다.
 *
 * <h2>화면에 Alertmanager를 적지 않는다</h2>
 *
 * 도입되지 않은 기술 이름은 사용자 화면의 정보가 아니다. 왜 비어 있는지는 이 주석과
 * 티켓이 갖고, 화면은 지금 제공되는 것만 말한다. 공급원이 생기면 그때 표를 되살린다 —
 * 열 이름은 제품 결정이라 API 모양이 정해진 뒤에 다시 적는 편이 정확하다.
 */
export function RecentEvents() {
  return (
    /*
      카드 표면(흰 배경 · radius 18 · 같은 테두리와 그림자)은 옆 카드와 맞춘다. 달라야 할
      것은 무게이지 재질이 아니다. 세로 padding만 22px → 16px로 줄인다.

      `.gj-mon-detail`이 `align-items: start`라 이 카드가 짧아져도 Disk Capacity가
      늘어나거나 줄에 빈 칸이 생기지 않는다.
    */
    <div className="rounded-[18px] border border-brand-line bg-white px-6 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">RECENT EVENTS</p>
      <h3 className="mt-1.5 text-[13px] font-[750] text-brand-ink">최근 상태 변화</h3>
      <p className="mt-2 text-[12.5px] leading-[1.6] break-keep text-brand-faint">
        상태 변화 이력은 현재 수집하지 않습니다. 실시간 서비스 상태는 위 Infrastructure
        Map에서 확인할 수 있습니다.
      </p>
    </div>
  )
}
