import { Link } from 'react-router'
import { useAnalysisHistory } from '@/features/mypage/hooks/useAnalysisHistory'
import type { AnalysisHistory, AnalysisHistoryStatus } from '@/features/mypage/api/types'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import {
  ACCOUNT_CONNECTIONS,
  ANALYSIS_HISTORY,
  ANALYSIS_HISTORY_NOTE,
  LATEST_ANALYSIS_SUMMARY,
} from '@/mocks/fixtures/analysisFlow'
import type { AnalysisHistoryFixture } from '@/mocks/types'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 마이페이지 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `14 My Page`).
 *
 * v2 구조: hero(+재분석 CTA) → `372 / 956` split → 이력 표 → 각주.
 * 다른 화면과 달리 **패널이 왼쪽**이다. 계정·연결이 맥락이고 이력이 본문이기 때문이다.
 *
 * `GET /me`와 이력 조회 API가 develop에 없어 값은 디자인 fixture에서 온다
 * (`VITE_DESIGN_FIXTURES=on`). v2 아트보드도 프로필 영역에 `DESIGN MOCK`이라고 직접
 * 적어 두었으므로 화면에 그 배지를 남긴다 — `dev-user` · `SSAFY 12기 · 백엔드`는
 * 레이아웃 검증용 값이다.
 *
 * **`연결 해제`는 버튼으로 두지 않는다.** 되돌릴 수 없는 동작이라 눌러도 아무 일이
 * 없는 버튼으로 미리 만들면 위험하다. fixture가 켜져 있어도 마찬가지다 — 값이 있는
 * 것과 동작이 있는 것은 다르다. 해당 API가 생길 때 같은 자리에 추가한다.
 *
 * 이력 표의 상태 넷이 서로 다른 색인 것이 중요하다(SUCCEEDED · PARTIAL · FAILED).
 * 실패와 부분 완료를 같은 색으로 칠하지 않는다는 것이 화면 15의 규칙이다.
 */
const HISTORY_COLUMNS = ['일시', 'REPOSITORY', '결과', '상태'] as const
const HISTORY_TEMPLATE = '170px minmax(0,1fr) minmax(0,1fr) 90px'

/** v2가 나열하는 연결 축. 상태 값은 조회 API가 준다. */
const CONNECTIONS = [
  { name: 'SSAFY 계정', description: '로그인 · 서비스 접근' },
  { name: 'GitHub', description: '읽기 전용 · 분석 대상 Repository 접근' },
] as const

/**
 * 이력 한 줄의 표시 모양 · 티켓 S15P21E102-281.
 *
 * `status`가 계약의 7종과 fixture의 `PARTIAL`을 함께 받는다. 명세 v0.1은 부분 성공을
 * `PARTIAL_SUCCEEDED`로 적고 fixture는 `PARTIAL`로 적어 두 어휘가 공존한다 — 어느
 * 쪽으로 맞출지는 BE 구현이 정하며 계약 문서 미결에 올렸다. 지금 한쪽을 지우면 다른
 * 쪽 값이 배지 없이 그려진다.
 */
type HistoryStatus = AnalysisHistoryStatus | 'PARTIAL'

interface HistoryRow {
  id: string
  at: string
  repositories: string
  resultText: string
  status: HistoryStatus
}

/**
 * 이력 상태 배지. `JobStatus`를 쓰지 않는 이유는 부분 성공이 그 enum에 없기 때문이다.
 *
 * 진행 중 상태(`QUEUED`·`RUNNING`·`RATE_LIMITED`)도 둔다. 이력을 보는 동안 다른 탭에서
 * 분석을 걸어 두면 종료 전 행이 표에 올라온다 — 빠뜨리면 그 행만 배지 없이 그려진다.
 */
const HISTORY_STATUS_CLASS: Readonly<Record<HistoryStatus, string>> = {
  QUEUED: 'bg-tone-neutral-bg text-tone-neutral',
  RUNNING: 'bg-tone-neutral-bg text-tone-neutral',
  RATE_LIMITED: 'bg-tone-caution-bg text-tone-caution',
  SUCCEEDED: 'bg-tone-success-bg text-tone-success',
  PARTIAL_SUCCEEDED: 'bg-tone-caution-bg text-tone-caution',
  PARTIAL: 'bg-tone-caution-bg text-tone-caution',
  FAILED: 'bg-tone-danger-bg text-tone-danger',
  CANCELED: 'bg-tone-neutral-bg text-tone-neutral',
}

/**
 * 분석 시각 표기.
 *
 * 서버는 UTC ISO-8601을 보낸다(명세 공통 규약). 상대 표기("오늘 10:42")는 보는 시점에
 * 따라 달라져 서버가 만들 수 없으므로 화면이 환산한다 — 표시 환산이지 판정이 아니다.
 */
function formatAnalyzedAt(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) {
    return iso
  }
  return at.toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function toHistoryRows(history: AnalysisHistory | undefined): HistoryRow[] {
  return (history?.items ?? []).map((item) => ({
    id: item.analysisId,
    at: formatAnalyzedAt(item.analyzedAt),
    repositories: item.repositories.join(' · '),
    resultText: item.resultText,
    status: item.status,
  }))
}

export function MyPage() {
  /*
   * 계정·연결 카드와 최근 분석 요약은 아직 붙이지 않았다 · 티켓 S15P21E102-281.
   *
   * 값이 **모자라서**이지 엔드포인트가 없어서가 아니다.
   *
   *   - 계정·연결: `GET /auth/me`(티켓 246, BE 구현됨)가 주는 것은 `displayName`·
   *     `avatarUrl`·`githubConnected`·`role` 넷이다. 이 카드는 소속(`SSAFY 12기 ·
   *     백엔드`)과 연결 상세(`@handle · 읽기 전용 · Repository 4개 접근`)를 함께
   *     그리는데 그 값을 주는 조회가 없다.
   *   - 최근 분석 요약: 저장소 수·기술 수·L2 이상 수는 `GET /me/profile`의 `summary`가
   *     주지만 `snapshotDate`에 해당하는 값이 없다.
   *
   * 있는 값만으로 채우고 나머지를 지어내면 화면이 사실이 아닌 것을 주장한다. 두 카드는
   * 값이 없으면 `StateCard`를 그리도록 되어 있어 지금 상태가 정확하다. 모자란 필드는
   * 계약 문서 미결에 올렸다.
   */
  const account = withDesignFixture<typeof ACCOUNT_CONNECTIONS | null>(
    null,
    () => ACCOUNT_CONNECTIONS,
  )
  const latest = withDesignFixture<typeof LATEST_ANALYSIS_SUMMARY | null>(
    null,
    () => LATEST_ANALYSIS_SUMMARY,
  )
  const historyQuery = useAnalysisHistory()
  const history = withDesignFixture<readonly HistoryRow[]>(toHistoryRows(historyQuery.data), () =>
    ANALYSIS_HISTORY.map((item: AnalysisHistoryFixture, index) => ({ ...item, id: `fixture-${index}` })),
  )

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="MY PAGE"
          title="계정 · 연결 · 분석 이력"
          description="GitHub 분석은 언제든 다시 실행할 수 있습니다. 새 Commit이 추가되면 재분석으로 Evidence를 갱신하세요."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <DesignMockBadge />
          <Link
            to="/onboarding/repositories"
            className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            GitHub 다시 분석
          </Link>
        </div>
      </div>

      {/* v2는 패널을 왼쪽에 둔다. 계정이 맥락, 이력이 본문이다. */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-[372px_minmax(0,1fr)]">
        <div className="grid gap-4">
          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">ACCOUNT</p>
            {account === null ? (
              <>
                <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
                  내 계정
                </h2>
                <div className="mt-4">
                  <StateCard
                    kind="PREPARING"
                    title="계정 정보를 아직 불러올 수 없어요"
                    description="이름과 소속은 조회 API가 준비되면 표시합니다. 화면에서 만들지 않습니다."
                  />
                </div>
              </>
            ) : (
              <>
                <h2 className="mt-1.5 text-[20px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
                  {account.displayName}
                </h2>
                <p className="mt-1 text-[12.5px] text-brand-muted">{account.affiliation}</p>
              </>
            )}
          </section>

          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
              CONNECTIONS
            </p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              두 계정은 따로 연결됩니다
            </h2>

            <ul className="mt-4 grid gap-2">
              {CONNECTIONS.map((connection, index) => {
                const live = account === null ? null : index === 0 ? account.ssafy : account.github
                return (
                  <li
                    key={connection.name}
                    className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-[750] text-brand-ink">
                          {connection.name}
                        </p>
                        <p className="mt-0.5 text-[11.5px] leading-[1.5] text-brand-muted">
                          {live?.detail ?? connection.description}
                        </p>
                      </div>
                      {/*
                        `SIGNED IN`·`CONNECTED`는 사실을 주장하는 값이라 조회 없이
                        쓰지 않는다. 값이 없으면 배지를 그리지 않는다.
                      */}
                      {live !== null && (
                        <span className="shrink-0 rounded-full bg-tone-success-bg px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] text-tone-success">
                          {live.status}
                        </span>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>

            <Link
              to="/onboarding/repositories"
              className="mt-4 block rounded-xl border border-brand-line bg-white px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              Repository 다시 선택
            </Link>

            <p className="mt-4 text-[11.5px] leading-[1.65] text-brand-faint">
              {account?.note ??
                'SSAFY 계정과 GitHub 계정은 별도로 연결됩니다. GitHub 연결을 해제하면 새 분석은 중단되지만 기존 이력은 유지됩니다.'}
            </p>
          </section>
        </div>

        <div className="grid gap-4">
          <DataRegion
            eyebrow="LATEST ANALYSIS"
            title="최근 분석"
            hint="이 분석의 결과가 Evidence · 공고 매칭 화면의 기준입니다."
            action={
              latest === null ? undefined : (
                <span className="shrink-0 rounded-full bg-tone-success-bg px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] text-tone-success">
                  {latest.status}
                </span>
              )
            }
          >
            {latest === null ? (
              <StateCard
                kind="PREPARING"
                title="최근 분석을 아직 불러올 수 없어요"
                description="분석 시각과 결과 요약은 이력 조회 API가 준비되면 표시합니다."
              />
            ) : (
              <>
                <p className="text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                  {latest.at}
                </p>
                <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { label: 'Repository', value: String(latest.repositoryCount) },
                    { label: '확인된 기술', value: String(latest.techCount) },
                    { label: 'Personal L2 이상', value: String(latest.personalL2OrAbove) },
                    { label: 'Snapshot', value: latest.snapshotDate },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className="rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-3"
                    >
                      <dt className="text-[11.5px] text-brand-faint">{item.label}</dt>
                      <dd className="mt-1 text-[15px] font-[750] tabular-nums text-brand-ink">
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </>
            )}

            <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
              <Link
                to="/evidence"
                className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
              >
                My Evidence 열기
              </Link>
              <Link
                to="/jobs"
                className="rounded-xl border border-brand-line bg-white px-5 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
              >
                공고 매칭
              </Link>
            </div>
          </DataRegion>

          <DataRegion
            eyebrow="HISTORY"
            title="분석 이력"
            hint="과거 분석은 그 시점의 Snapshot으로 고정됩니다. 최신 Level은 최근 분석만 반영합니다."
          >
            <div className="overflow-hidden rounded-[14px] border border-brand-line">
              <div
                className="hidden gap-4 border-b border-brand-line bg-[#F7F9FC] px-4 py-2.5 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
                style={{ gridTemplateColumns: HISTORY_TEMPLATE }}
              >
                {HISTORY_COLUMNS.map((label) => (
                  <span key={label} className="truncate">
                    {label}
                  </span>
                ))}
              </div>
              <div className="p-3">
                {history.length === 0 ? (
                  <StateCard
                    kind="PREPARING"
                    title="분석 이력을 아직 불러올 수 없어요"
                    description="언제 어떤 저장소를 분석했고 결과가 어땠는지 이 표에 쌓입니다. 실패와 부분 완료는 구분해 표시합니다."
                  />
                ) : (
                  <div className="divide-y divide-[#F1F4F9]">
                    {history.map((item) => (
                      <div
                        key={item.id}
                        className="grid items-center gap-4 px-1.5 py-3 max-lg:grid-cols-1"
                        style={{ gridTemplateColumns: HISTORY_TEMPLATE }}
                      >
                        <p className="text-[12.5px] font-[750] text-brand-ink">{item.at}</p>
                        <p className="truncate text-[12.5px] text-brand-muted">
                          {item.repositories}
                        </p>
                        <p className="text-[12.5px] text-brand-muted">{item.resultText}</p>
                        <span
                          className={`w-fit rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] ${
                            HISTORY_STATUS_CLASS[item.status]
                          }`}
                        >
                          {item.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {history.length > 0 && (
              <p className="mt-3 text-[11.5px] leading-[1.65] text-brand-faint">
                {ANALYSIS_HISTORY_NOTE}
              </p>
            )}
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        분석은 GitHub의 공개·허용된 저장소만 읽습니다. Evidence는 재분석 시점의 Commit 기준으로
        갱신되며, 과거 분석 결과를 덮어쓰지 않습니다.
      </PageFootnote>
    </div>
  )
}
