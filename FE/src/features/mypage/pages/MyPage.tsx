import { Link } from 'react-router'
import { useAnalysisHistory } from '@/features/mypage/hooks/useAnalysisHistory'
import type { AnalysisHistory, AnalysisHistoryStatus } from '@/features/mypage/api/types'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import {
  ACCOUNT_CONNECTIONS,
  ANALYSIS_HISTORY,
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

/**
 * 근거 등급 · 분석 전 안내에 쓴다.
 *
 * 이력의 `최고 L1` 같은 값이 무엇인지 알려면 이 표가 필요한데, 분석을 한 번도 안 한
 * 사람에게는 그 값을 볼 화면 자체가 없다. 빈 카드가 그 자리를 대신한다.
 */
const EVIDENCE_LEVELS = [
  { code: 'L0', label: '의존성 선언' },
  { code: 'L1', label: '설정 · 초기화' },
  { code: 'L2', label: '실제 사용 코드' },
] as const

interface HistoryRow {
  id: string
  /** `2026.09.16`. 표에서 세로로 읽히도록 자릿수를 고정한 표기다. */
  at: string
  /** `16:01`. 날짜와 무게를 달리 주려고 따로 든다. 픽스처에는 없어 빈 문자열이다. */
  atTime: string
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
 * `toLocaleString('ko-KR')`의 기본형은 `2026. 9. 16. 16:01`이라 점이 세 번 찍히고
 * 월·일의 자릿수가 들쭉날쭉해 표에서 세로로 읽히지 않는다. 자릿수를 채운
 * `2026.09.16`으로 두고 시각을 분리한다 — 화면이 날짜와 시각에 다른 무게를 줄 수 있다.
 *
 * 오늘·어제만 이름으로 부른다. 이력에서 가장 자주 보는 두 줄이고, 사람이 "어제 돌린
 * 그것"으로 기억하기 때문이다. 그보다 오래된 기록까지 상대 표기로 두면(사흘 전, 지난주)
 * 줄마다 기준이 달라져 두 기록의 간격을 눈으로 잴 수 없다.
 *
 * 상대 표기는 보는 시점에 따라 달라지므로 서버가 만들 수 없다. 화면이 환산한다.
 */
function formatAnalyzedAt(iso: string): { date: string; time: string } {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) {
    return { date: iso, time: '' }
  }
  const pad = (value: number) => String(value).padStart(2, '0')
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`

  const now = new Date()
  if (isSameDay(at, now)) {
    return { date: '오늘', time }
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (isSameDay(at, yesterday)) {
    return { date: '어제', time }
  }
  return { date: `${at.getFullYear()}.${pad(at.getMonth() + 1)}.${pad(at.getDate())}`, time }
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

function toHistoryRows(history: AnalysisHistory | undefined): HistoryRow[] {
  return (history?.items ?? []).map((item) => ({
    id: item.analysisId,
    at: formatAnalyzedAt(item.analyzedAt).date,
    atTime: formatAnalyzedAt(item.analyzedAt).time,
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
  const historyQuery = useAnalysisHistory()
  const history = withDesignFixture<readonly HistoryRow[]>(toHistoryRows(historyQuery.data), () =>
    ANALYSIS_HISTORY.map((item: AnalysisHistoryFixture, index) => ({
      ...item,
      atTime: '',
      id: `fixture-${index}`,
    })),
  )
  /*
    최근 분석은 이력의 첫 줄이다. 목록이 최근 순이라 따로 조회하지 않는다 — 같은 것을
    두 번 부르면 두 카드가 서로 다른 분석을 가리키는 순간이 생긴다.
  */
  const latest = history[0] ?? null

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
          {/*
            분석이 하나도 없을 때와 있을 때는 화면이 답해야 하는 질문이 다르다.

            없을 때 물음은 "무엇을 해야 하나"뿐이다. 그런데 좌우로 벌린 배치를 그대로
            쓰면 왼쪽 글과 오른쪽 버튼 사이가 텅 비고, 아래 이력 표까지 같은 말을 한 번
            더 해서 화면 두 칸이 "없어요"로 채워진다. 그래서 이 경우만 가운데로 모으고
            이력 표는 그리지 않는다.

            있을 때 물음은 "언제 무엇을 얼마나"이고, 그때는 좌우 배치가 맞다.
          */}
          {latest === null ? (
            <section className="grid overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)] lg:grid-cols-[1fr_300px]">
              {/*
                오른쪽 등급 패널이 세로 가운데 정렬이라 왼쪽 글이 위에 붙어 있으면 두
                칸의 무게중심이 어긋난다. 같은 축에 맞춘다.
              */}
              {/*
                오른쪽 등급 패널이 세로 가운데 정렬이라 왼쪽도 같은 축에 맞춘다. 가로도
                가운데로 두는 편이 낫다 — 빈 상태의 이 칸에는 읽을 순서가 하나뿐이라
                왼쪽 정렬이 만드는 세로선이 지킬 것이 없다.
              */}
              <div className="flex flex-col items-center justify-center px-8 py-8 text-center">
                <p className="text-[10.5px] font-extrabold tracking-[0.16em] text-brand-600">
                  LATEST ANALYSIS
                </p>
                <h2 className="mt-2.5 text-[19px] font-[800] tracking-[-0.02em] text-brand-ink">
                  {historyQuery.isPending
                    ? '최근 분석을 불러오는 중이에요'
                    : '아직 분석한 적이 없어요'}
                </h2>
                <p className="mt-2 max-w-[420px] text-[13px] leading-[1.7] text-brand-muted">
                  {historyQuery.isPending
                    ? '잠시만 기다려 주세요.'
                    : 'Repository를 고르면 그 저장소의 의존성과 설정에서 기술 사용 근거를 찾습니다. 읽기 전용이고 고른 저장소만 봅니다.'}
                </p>
                {!historyQuery.isPending && (
                  <Link
                    to="/onboarding/repositories"
                    className="mt-5 rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-6 py-3 text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
                  >
                    GitHub 분석하기
                  </Link>
                )}
              </div>

              {/*
                빈 자리를 여백으로 두지 않고 이 제품이 무엇을 찾는지로 채운다. 분석을
                한 번도 안 한 사람에게 가장 필요한 설명이 "근거에 등급이 있다"는 것이고,
                그게 곧 분석이 끝난 뒤 이력에 찍히는 `최고 L1` 같은 값의 뜻이다.
              */}
              <aside className="flex flex-col justify-center gap-2.5 border-brand-line bg-[linear-gradient(160deg,#F7FAFF,#EAF1FF)] px-6 py-7 max-lg:border-t lg:border-l">
                {EVIDENCE_LEVELS.map((level) => (
                  <div
                    key={level.code}
                    className="flex items-center gap-2.5 rounded-[10px] border border-brand-line bg-white px-3 py-2.5"
                  >
                    <span className="rounded-[5px] bg-tone-accent-bg px-1.5 py-1 font-evidence text-[10px] font-bold text-brand-600">
                      {level.code}
                    </span>
                    <span className="text-[12px] text-brand-muted">{level.label}</span>
                  </div>
                ))}
              </aside>
            </section>
          ) : (
            <section className="relative overflow-hidden rounded-[20px] border border-brand-line bg-[linear-gradient(160deg,#FFFFFF_0%,#F7FAFF_58%,#EEF4FF_100%)] px-6 py-5 shadow-[0_18px_40px_rgba(25,47,81,0.09)]">
              {/* 왼쪽 세로 악센트. 카드가 목록이 아니라 지금 상태라는 표시다. */}
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 w-[3px] bg-[linear-gradient(180deg,#2F5EEB,#5B8DFF)]"
              />

              <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
                <div className="min-w-0">
                  <p className="text-[10.5px] font-extrabold tracking-[0.16em] text-brand-600">
                    LATEST ANALYSIS
                  </p>

                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <p className="flex items-baseline gap-2 leading-none">
                      <span className="text-[21px] font-[800] tracking-[-0.01em] tabular-nums text-brand-ink">
                        {latest.at}
                      </span>
                      <span className="text-[15px] font-semibold tabular-nums text-brand-muted">
                        {latest.atTime}
                      </span>
                    </p>
                    <span
                      className={`shrink-0 rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] ${
                        HISTORY_STATUS_CLASS[latest.status]
                      }`}
                    >
                      {latest.status}
                    </span>
                  </div>

                  <dl className="mt-3.5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px]">
                    <div className="flex items-center gap-1.5">
                      <dt className="text-brand-faint">Repository</dt>
                      <dd className="font-evidence font-[750] text-brand-ink-soft">
                        {latest.repositories || '이름 기록 없음'}
                      </dd>
                    </div>
                    <span aria-hidden className="h-3 w-px bg-brand-line" />
                    <div className="flex items-center gap-1.5">
                      <dt className="text-brand-faint">결과</dt>
                      <dd className="font-[750] text-brand-ink-soft">{latest.resultText}</dd>
                    </div>
                  </dl>
                </div>

                {/* 버튼은 카드 안 오른쪽이다. 아래로 내리면 카드가 두 배로 길어진다. */}
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <Link
                    to="/evidence"
                    className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-4 py-2.5 text-[13px] font-[750] text-white shadow-[0_10px_22px_rgba(47,94,235,0.26)]"
                  >
                    My Evidence 열기
                  </Link>
                  <Link
                    to="/jobs"
                    className="rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                  >
                    공고 매칭
                  </Link>
                </div>
              </div>
            </section>
          )}

          {/*
            이력이 하나도 없으면 이 섹션을 그리지 않는다. 위 카드가 이미 "없어요"를
            말하고 분석을 시작할 길까지 주는데, 아래에 같은 말을 한 번 더 두면 화면 두
            칸이 빈 상자로 채워진다.

            정책 한 줄("과거 분석은 Snapshot 시점으로 고정")은 페이지 각주에만 남긴다.
            같은 문장이 hint·표 아래·각주 세 곳에 있었다.
          */}
          {history.length > 0 && (
            <DataRegion eyebrow="HISTORY" title="분석 이력">
              <div className="overflow-hidden rounded-[14px]">
                <div
                  className="hidden gap-4 border-b border-brand-line px-2.5 py-2.5 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
                  style={{ gridTemplateColumns: HISTORY_TEMPLATE }}
                >
                  {HISTORY_COLUMNS.map((label) => (
                    <span key={label} className="truncate">
                      {label}
                    </span>
                  ))}
                </div>

                <div className="divide-y divide-[#F1F4F9]">
                  {history.map((item) => (
                    <div
                      key={item.id}
                      className="grid items-center gap-4 rounded-[10px] px-2.5 py-3.5 transition-colors max-lg:grid-cols-1 hover:bg-[#F8FAFD]"
                      style={{ gridTemplateColumns: HISTORY_TEMPLATE }}
                    >
                      <p className="flex items-baseline gap-1.5">
                        <span className="text-[13px] font-[750] tabular-nums text-brand-ink">
                          {item.at}
                        </span>
                        <span className="text-[12px] tabular-nums text-brand-faint">
                          {item.atTime}
                        </span>
                      </p>
                      {/*
                        저장소는 고정폭 글꼴이다. `owner/name`이 사람 이름이 아니라
                        식별자여서, 본문 글꼴로 쓰면 결과 문구와 같은 무게로 읽힌다.
                      */}
                      <p className="truncate font-evidence text-[12px] text-brand-ink-soft">
                        {item.repositories || '이름 기록 없음'}
                      </p>
                      <p className="truncate text-[12.5px] text-brand-muted">{item.resultText}</p>
                      <span
                        className={`w-fit justify-self-start rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] lg:justify-self-end ${
                          HISTORY_STATUS_CLASS[item.status]
                        }`}
                      >
                        {item.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <p className="mt-3 text-[11.5px] text-brand-faint">
                이력 {historyQuery.data?.totalCount ?? history.length}건
              </p>
            </DataRegion>
          )}
        </div>
      </div>

      <PageFootnote>
        분석은 GitHub의 공개·허용된 저장소만 읽습니다. Evidence는 재분석 시점의 Commit 기준으로
        갱신되며, 과거 분석 결과를 덮어쓰지 않습니다.
      </PageFootnote>
    </div>
  )
}
