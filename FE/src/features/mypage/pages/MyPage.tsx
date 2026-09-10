import { Link } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { ListShell, TableScaffold } from '@/shared/ui/Scaffold'
import { StateCard } from '@/shared/ui/StateCard'

/** Final `#mypage` 이력 목록의 컬럼. 값이 아니라 이력이 어떤 축으로 쌓이는지의 정의다. */
const HISTORY_COLUMNS = ['요청 시각', '대상 Repository', '확인된 기술', '결과'] as const
const HISTORY_TEMPLATE = '1fr 1.6fr .9fr 120px'

/**
 * Final `#mypage`가 나열하는 연결 축. `CONNECTED` · `SIGNED IN`은 사실을 주장하는
 * 값이라 쓰지 않는다. 조회 API가 없어 연결 여부를 알 수 없기 때문이다.
 */
const CONNECTIONS = [
  { name: 'GitHub', description: '저장소 읽기 전용 권한으로 분석에 사용합니다.' },
  { name: 'SSAFY 계정', description: 'GitHub 계정과는 별도로 연결됩니다.' },
] as const

/**
 * My Page · History 초안 · 티켓 S15P21E102-192.
 *
 * 시각 기준: Final `section#mypage` — hero → `846 372` split(분석 이력 | 연결 상태).
 *
 * 사용자 이름·아바타·연결 계정·분석 이력을 표시하지 않는다. `GET /me`가 develop에
 * 없어서(계약 1-4의 `['me']` 행이 BE 미구현) 사용자 정보를 얻을 수 없고, 분석 이력
 * 조회 API도 없다. Final의 `오늘 10:42` 같은 값은 demo라 옮기지 않는다.
 *
 * 우측 패널의 연결 해제·데이터 삭제도 버튼으로 두지 않았다. 해당 API가 없어 눌러도
 * 아무 일이 없고, 되돌릴 수 없는 동작을 동작하지 않는 버튼으로 두면 위험하다.
 */
export function MyPage() {
  return (
    <div>
      <PageHero
        eyebrow="MY PAGE"
        title="분석 이력과 연결 상태"
        description="GitHub 분석은 언제든 다시 실행할 수 있습니다. 지난 분석과 연결 상태를 이 화면에서 확인합니다."
      />

      <div className="gj-split mt-7">
        <DataRegion
          eyebrow="ANALYSIS HISTORY"
          title="분석 이력"
          hint="요청 시각 · 대상 Repository · 결과 상태 순으로 표시됩니다."
        >
          {/* 이력이 쌓이는 축은 지금 보여줄 수 있다. 가짜 이력 행은 만들지 않는다. */}
          <TableScaffold columns={HISTORY_COLUMNS} template={HISTORY_TEMPLATE}>
            <StateCard
              kind="PREPARING"
              title="분석 이력을 아직 불러올 수 없어요"
              description="지난 분석과 Snapshot 비교를 돌려주는 조회 API가 준비되면 이 표에 쌓입니다."
            />
          </TableScaffold>
        </DataRegion>

        <aside className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">CONNECTION</p>
          <h2 className="mt-1.5 text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
            연결 상태
          </h2>
          {/*
            연결 축만 세우고 상태는 `PREPARING`으로 둔다. `CONNECTED`처럼 사실을
            주장하는 값은 조회 API가 있어야 쓸 수 있다.
          */}
          <div className="mt-4 grid gap-2.5">
            {CONNECTIONS.map((item) => (
              <ListShell
                key={item.name}
                name={item.name}
                description={item.description}
                status="PREPARING"
              />
            ))}
          </div>
          <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-muted">
            연결 해제와 데이터 삭제는 해당 API가 준비된 뒤 이 자리에서 제공됩니다. 되돌릴 수
            없는 동작이라 눌리지 않는 버튼으로 미리 두지 않습니다.
          </p>
        </aside>
      </div>

      <div className="mt-4">
        <DataRegion
          eyebrow="START"
          title="지금 할 수 있는 것"
          hint="저장소를 골라 분석을 요청하는 흐름은 지금 동작합니다."
          action={
            <Link
              to="/onboarding/repositories"
              className="shrink-0 rounded-xl bg-[linear-gradient(135deg,var(--color-brand-600),var(--color-brand-400))] px-[22px] py-[14px] text-[14px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)] transition-shadow hover:shadow-[0_16px_32px_rgba(47,94,235,0.34)]"
            >
              저장소 선택으로 이동
            </Link>
          }
        >
          <p className="max-w-[64ch] text-[13px] leading-[1.7] text-brand-muted">
            Repository를 여러 개 골라 함께 분석을 시작할 수 있습니다. 저장소마다 독립적으로
            분석되고 분석 ID도 따로 생깁니다.
          </p>
        </DataRegion>
      </div>

      <PageFootnote>
        분석 결과는 Evidence(파일 · 설정 · Commit)로 제시되며 점수로 환산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
