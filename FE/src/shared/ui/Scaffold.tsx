import type { ReactNode } from 'react'

/**
 * 데이터가 없어도 남는 구조 · 티켓 S15P21E102-192.
 *
 * 2026-09-10 Design Audit의 결론이 이 파일의 이유다. Final HTML을 React로 옮기면서
 * 표의 컬럼 헤더, 지표 행의 라벨, 출처 목록 같은 **골격**이 통째로 사라지고 화면마다
 * 상태 카드 한 장만 남았다. 그래서 데이터가 없는 화면이 "준비 중인 제품"이 아니라
 * "아직 안 만든 화면"으로 읽혔다.
 *
 * 여기 있는 것은 전부 **데이터가 필요 없는 구조**다. 컬럼 이름과 지표 이름은 제품이
 * 무엇을 보여줄지에 대한 정의이지 사용자 데이터가 아니다. 그래서 API가 없어도 그릴 수
 * 있고, 그려야 무엇이 들어올 자리인지 전달된다.
 *
 * 반대로 **행과 값은 절대 만들지 않는다.** 가짜 기술명·가짜 수치·가짜 사용자는 이
 * 파일에 없고 앞으로도 넣지 않는다. 값 자리는 호출부가 `StateCard`로 채운다.
 */

/**
 * 표 골격.
 *
 * Final `#evidence`의 표가 기준이다. 컬럼 5개에 grid-template-columns
 * `1.2fr .7fr .7fr 1.6fr 120px`. 헤더는 그대로 두고 본문만 비운다.
 *
 * `<table>`이 아니라 grid인 것도 Final을 따른 것이다. 열 폭을 fr로 잡아야 846px
 * 영역과 1600px 셸에서 같은 비율을 유지한다.
 *
 * 좁은 화면에서는 헤더를 감춘다. 컬럼 5개를 375px에 밀어 넣으면 글자가 겹친다.
 * 그 구간에서는 본문 상태 카드만 남는데, 표의 의미는 데이터가 들어온 뒤에 살아나므로
 * 지금 단계에서는 이것으로 충분하다.
 */
export function TableScaffold({
  columns,
  template,
  children,
}: {
  /** 컬럼 이름. 제품 정의이지 데이터가 아니다 */
  columns: readonly string[]
  /** grid-template-columns 값. Final의 해당 표에서 읽어온 값을 그대로 넘긴다 */
  template: string
  /** 값 자리. 데이터가 없으면 `StateCard`를 넘긴다 */
  children: ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-brand-line">
      <div
        className="hidden gap-3 border-b border-brand-line bg-[#F7F9FC] px-4 py-2.5 lg:grid"
        style={{ gridTemplateColumns: template }}
      >
        {columns.map((label) => (
          <span
            key={label}
            className="truncate text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint"
          >
            {label}
          </span>
        ))}
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

/**
 * 지표 한 칸의 껍데기.
 *
 * Final `#evidence` 상단의 `repeat(4,1fr)` 지표 행에 대응한다. 라벨과 단위 설명은
 * 정적 정의라 지금 보여줄 수 있고, 숫자가 들어갈 자리만 비워 둔다.
 *
 * 비어 있는 값 자리를 `0`이나 `-`로 채우지 않는다. `0`은 "분석했더니 없었다"라는
 * 거짓 사실이 되고, `-`는 무엇을 기다리는지 알려주지 않는다. 대신 왜 비었는지를
 * `note`로 말한다.
 */
export function StatShell({
  label,
  note,
  caption,
}: {
  /** 지표 이름 */
  label: string
  /** 값 자리에 들어갈 짧은 상태 문구. 숫자를 넣지 않는다 */
  note: string
  /** 기준 설명 */
  caption?: string
}) {
  return (
    <div className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
      <p className="text-[12px] font-medium text-brand-muted">{label}</p>
      <p className="mt-1.5 text-[13px] font-[750] tracking-[-0.01em] text-brand-faint">{note}</p>
      {caption !== undefined && (
        <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">{caption}</p>
      )}
    </div>
  )
}

/**
 * 목록 한 줄의 껍데기.
 *
 * Final `#mypage`의 분석 이력·연결 상태, `#trend`의 출처 목록이 같은 모양이다.
 * 왼쪽에 항목 이름과 설명, 오른쪽에 상태. 이 골격이 있으면 "이력이 쌓이는 자리"라는
 * 것이 데이터 없이도 전달된다.
 *
 * `status`는 정적 문자열이다. `CONNECTED`처럼 사실을 주장하는 값은 호출부가 넘기지
 * 않는다. 연결 여부를 알려면 API가 필요한데 아직 없다.
 */
export function ListShell({
  name,
  description,
  status,
}: {
  name: string
  description: string
  status: string
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
      <div className="min-w-0">
        <p className="text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">{name}</p>
        <p className="mt-1 text-[12.5px] leading-[1.55] text-brand-muted">{description}</p>
      </div>
      <span className="shrink-0 rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.1em] text-tone-neutral">
        {status}
      </span>
    </div>
  )
}

/**
 * 읽기 전용 출처 구분.
 *
 * 현재 MVP `#trend`는 채용공고 · GitHub 두 출처를 구분한다. 하지만
 * 전환할 데이터가 아직 없다. **누를 수 있는데 아무 일도 없는 탭은 만들지 않는다**
 * (Interaction Safety). 그래서 같은 정보를 정적 범례로만 보여준다.
 *
 * 출처를 굳이 지금 노출하는 이유는, 이 제품이 출처를 합산하지 않고 각각 따로 본다는
 * 원칙 자체가 화면에서 읽혀야 하기 때문이다(PROJECT_GUIDE §1).
 */
export function SourceLegend({ sources }: { sources: readonly string[] }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {sources.map((source) => (
        <li
          key={source}
          className="rounded-full border border-brand-line bg-white/70 px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
        >
          {source}
        </li>
      ))}
    </ul>
  )
}
