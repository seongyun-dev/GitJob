import { Link } from 'react-router'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 마이페이지 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `14 My Page`).
 *
 * v2 구조: hero(+재분석 CTA) → `372 / 956` split → 이력 표 → 각주.
 * 다른 화면과 달리 **패널이 왼쪽**이다. 계정·연결이 맥락이고 이력이 본문이기 때문이다.
 *
 * 사용자 이름·계정·연결 상태·이력을 표시하지 않는다.
 * - v2 아트보드가 프로필 영역에 `DESIGN MOCK`이라고 직접 적어 두었다. `dev-user`,
 *   `SSAFY 12기 · 백엔드`는 레이아웃 검증용 값이다.
 * - `GET /me`와 이력 조회 API가 develop에 없다.
 * - `SIGNED IN` · `CONNECTED`는 사실을 주장하는 값이라 조회 없이 쓸 수 없다.
 *
 * `연결 해제`는 버튼으로 두지 않는다. 되돌릴 수 없는 동작이라 눌러도 아무 일이 없는
 * 버튼으로 미리 만들면 위험하다. 해당 API가 생길 때 같은 자리에 추가한다.
 */
const HISTORY_COLUMNS = ['일시', 'REPOSITORY', '결과', '상태'] as const
const HISTORY_TEMPLATE = '170px minmax(0,1fr) minmax(0,1fr) 90px'

/** v2가 나열하는 연결 축. 상태 값은 조회 API가 준다. */
const CONNECTIONS = [
  { name: 'SSAFY 계정', description: '로그인 · 서비스 접근' },
  { name: 'GitHub', description: '읽기 전용 · 분석 대상 Repository 접근' },
] as const

export function MyPage() {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="MY PAGE"
          title="계정 · 연결 · 분석 이력"
          description="GitHub 분석은 언제든 다시 실행할 수 있습니다. 새 Commit이 추가되면 재분석으로 Evidence를 갱신하세요."
        />
        <Link
          to="/onboarding/repositories"
          className="shrink-0 rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
        >
          GitHub 다시 분석
        </Link>
      </div>

      {/* v2는 이 화면만 패널이 왼쪽이다. 계정·연결이 맥락이고 이력이 본문이다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[372px_minmax(0,1fr)]">
        <div className="grid gap-4">
          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">ACCOUNT</p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              계정 정보
            </h2>
            <div className="mt-4">
              <StateCard
                kind="PREPARING"
                title="계정 정보 준비 중"
                description="로그인한 계정과 표시 이름을 돌려주는 조회 API가 준비되면 표시합니다."
              />
            </div>
          </section>

          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
              CONNECTION
            </p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              연결 상태
            </h2>
            {/*
              연결 축만 세우고 상태는 대기로 둔다. `CONNECTED`처럼 사실을 주장하는
              값은 조회 API가 있어야 쓸 수 있다.
            */}
            <div className="mt-4 grid gap-2.5">
              {CONNECTIONS.map((item) => (
                <div
                  key={item.name}
                  className="flex items-start justify-between gap-4 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                >
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
                      {item.name}
                    </p>
                    <p className="mt-1 text-[12.5px] leading-[1.55] text-brand-muted">
                      {item.description}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.1em] text-tone-neutral">
                    PREPARING
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-muted">
              SSAFY 계정과 GitHub 계정은 별도로 연결됩니다. 연결 해제는 해당 API가 준비된 뒤 이
              자리에서 제공합니다. 되돌릴 수 없는 동작이라 눌리지 않는 버튼으로 미리 두지
              않습니다.
            </p>
          </section>
        </div>

        <div className="grid gap-4">
          <DataRegion
            eyebrow="LATEST"
            title="최근 분석"
            hint="가장 최근 분석의 대상 저장소와 결과 요약이 표시됩니다."
          >
            <StateCard
              kind="NO_DATA"
              title="아직 분석 기록이 없어요"
              description="저장소를 선택해 분석하면 결과 요약이 이 자리에 남습니다."
              action={
                <Link
                  to="/onboarding/repositories"
                  className="inline-block rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                >
                  저장소 선택으로
                </Link>
              }
            />
          </DataRegion>

          <DataRegion
            eyebrow="ANALYSIS HISTORY"
            title="분석 이력"
            hint="일시 · 대상 Repository · 결과 · 상태 순으로 쌓입니다."
          >
            <div className="overflow-hidden rounded-[14px] border border-brand-line">
              <div
                className="hidden gap-[18px] border-b border-brand-line bg-[#F7F9FC] px-4 py-2.5 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
                style={{ gridTemplateColumns: HISTORY_TEMPLATE }}
              >
                {HISTORY_COLUMNS.map((label) => (
                  <span key={label} className="truncate">
                    {label}
                  </span>
                ))}
              </div>
              <div className="p-3">
                <StateCard
                  kind="PREPARING"
                  title="분석 이력을 아직 불러올 수 없어요"
                  description="지난 분석과 Snapshot 비교를 돌려주는 조회 API가 준비되면 이 표에 쌓입니다."
                />
              </div>
            </div>
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        분석 결과는 Evidence(파일 · 설정 · Commit)로 제시되며 점수로 환산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
