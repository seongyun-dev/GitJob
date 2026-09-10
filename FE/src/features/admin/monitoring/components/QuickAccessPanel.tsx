import { Link } from 'react-router'
import type { MonitoringOverview } from '@/features/admin/monitoring/api/monitoringApi'

/**
 * Quick Access · 티켓 S15P21E102-210.
 *
 * **주소를 이 파일이 알지 않는다.** Grafana·Prometheus는 관리자망에만 열려 있고, 그
 * 주소를 FE 번들에 넣으면 공개 배포물에 사설 주소가 박힌다. 링크는 BE가 서버 설정에서
 * 읽어 `overview.links`로 준다(티켓 209).
 *
 * 설정되지 않은 링크는 회색 비활성 항목으로 남기고 `<a>`를 만들지 않는다. 눌러도 아무
 * 일이 없는 링크는 만들지 않는다는 규칙을 따르며, 자리를 아예 없애지 않는 이유는
 * "이 화면에서 Grafana로 갈 수 있다"는 것이 제품 정의이고 지금 빠진 것은 설정값뿐임을
 * 알려야 하기 때문이다.
 *
 * Technology Registry는 내부 화면이라 `Link`로 이동한다. Admin의 두 화면이 서로 오갈 수
 * 있어야 한다는 것이 이 티켓의 요구다.
 */

function ExternalLink({
  href,
  title,
  caption,
}: {
  href: string | null
  title: string
  caption: string
}) {
  if (href === null) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-[12px] border border-brand-line bg-[#F6F8FC] px-4 py-3.5 opacity-70">
        <div>
          <p className="text-[14px] font-bold text-brand-muted">{title}</p>
          <p className="mt-0.5 text-[12px] text-brand-faint">주소가 설정되지 않았습니다</p>
        </div>
      </div>
    )
  }

  return (
    <a
      href={href}
      // 관리자 도구를 새 탭에서 연다. 모니터링 화면을 떠나면 보고 있던 값을 잃는다.
      target="_blank"
      rel="noreferrer noopener"
      className="flex items-center justify-between gap-3 rounded-[12px] border border-brand-line bg-[#F6F8FC] px-4 py-3.5 text-brand-ink-soft transition-colors hover:border-brand-line-active hover:bg-tone-accent-bg"
    >
      <div>
        <p className="text-[14px] font-bold">{title}</p>
        <p className="mt-0.5 text-[12px] text-brand-faint">{caption}</p>
      </div>
      <span className="text-[13px] font-bold text-brand-600" aria-hidden>
        ↗
      </span>
    </a>
  )
}

export function QuickAccessPanel({ links }: { links: MonitoringOverview['links'] }) {
  return (
    <aside className="rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
        QUICK ACCESS
      </p>
      <h2 className="mt-2.5 text-[18px] font-[750] tracking-[-0.03em] text-brand-ink">
        상세 지표와 관리 화면
      </h2>

      <div className="mt-3.5 flex flex-col gap-2">
        <ExternalLink
          href={links.grafanaUrl}
          title="Grafana 상세 보기"
          caption="노드 · 컨테이너 대시보드"
        />
        <ExternalLink
          href={links.prometheusUrl}
          title="Prometheus 상세 보기"
          caption="타겟 상태 · 쿼리"
        />
      </div>

      <Link
        to="/admin/technology-candidates"
        className="mt-3.5 block rounded-[12px] bg-linear-to-br from-brand-600 to-brand-400 px-4 py-3.5 text-center text-[14px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)] transition-shadow hover:shadow-[0_16px_34px_rgba(47,94,235,0.32)]"
      >
        Technology Registry 관리 →
      </Link>
    </aside>
  )
}
