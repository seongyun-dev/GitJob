import { Link } from 'react-router'
import { useMe } from '@/features/auth/hooks/useMe'
import { useTechnologyProfile } from '@/features/evidence/hooks/useTechnologyProfile'
import { useTarget } from '@/features/matching/hooks/useMatching'
import {
  normalizeTargetRole,
  targetRoleDisplayName,
} from '@/features/matching/model/targetOptions'
import { useAnalysisHistory } from '@/features/mypage/hooks/useAnalysisHistory'
import type { AnalysisHistory, AnalysisHistoryStatus } from '@/features/mypage/api/types'
import { accountName, analysisSettingsRows } from '@/features/mypage/model/analysisSettings'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { ANALYSIS_HISTORY } from '@/mocks/fixtures/analysisFlow'
import type { AnalysisHistoryFixture } from '@/mocks/types'
import { DataRegion } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'

/**
 * 마이페이지 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `14 My Page`).
 *
 * v2 구조: hero(+재분석 CTA) → `372 / 956` split → 이력 표 → 각주.
 * 다른 화면과 달리 **패널이 왼쪽**이다. 계정·연결이 맥락이고 이력이 본문이기 때문이다.
 *
 * 왼쪽 두 카드는 티켓 S15P21E102-318에서 다시 짰다. v2 아트보드가 SSAFY 로그인을
 * 전제해 `내 계정`(소속)과 `계정 연결`(SSAFY · GitHub) 두 축을 그렸는데, SSAFY 로그인은
 * MVP에서 쓰지 않기로 했고 소속·연결 상세를 주는 조회도 없어 기본 상태가 `PREPARING`
 * 이었다. 정상 로그인한 사람이 자기 계정 화면에서 "불러올 수 없다"를 보는 상태였다.
 *
 * 지금은 있는 값만 그린다 — `ACCOUNT`는 `/auth/me`의 넷, `ANALYSIS SETTINGS`는
 * `/me/target`과 두 이동 버튼이다. 저장소 수는 `GET /me/technologies`의
 * `summary.repositoryCount`이며 선택이 아니라 **분석** 기준이다(`model/analysisSettings` 주석).
 *
 * 이력 표는 조회 API가 없어 값이 디자인 fixture에서 온다(`VITE_DESIGN_FIXTURES=on`).
 * 화면의 `DESIGN MOCK` 배지가 그 사실을 말한다.
 *
 * **`연결 해제`는 버튼으로 두지 않는다.** 되돌릴 수 없는 동작이라 눌러도 아무 일이
 * 없는 버튼으로 미리 만들면 위험하다. 해당 API가 생길 때 같은 자리에 추가한다.
 *
 * 이력 표의 상태 넷이 서로 다른 색인 것이 중요하다(SUCCEEDED · PARTIAL · FAILED).
 * 실패와 부분 완료를 같은 색으로 칠하지 않는다는 것이 화면 15의 규칙이다.
 */
const HISTORY_COLUMNS = ['일시', '저장소', '결과', '상태'] as const
const HISTORY_TEMPLATE = '170px minmax(0,1fr) minmax(0,1fr) 90px'

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

const HISTORY_STATUS_LABEL: Readonly<Record<HistoryStatus, string>> = {
  QUEUED: '대기 중',
  RUNNING: '분석 중',
  RATE_LIMITED: '잠시 지연',
  SUCCEEDED: '완료',
  PARTIAL_SUCCEEDED: '일부 완료',
  PARTIAL: '일부 완료',
  FAILED: '실패',
  CANCELED: '취소',
}

function userFacingText(value: string): string {
  return value
    .replaceAll('Repository', '저장소')
    .replace(/RATE_LIMIT(?:ED)?/g, '요청 제한으로 지연')
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
   * 계정 카드는 인증이 이미 쓰는 값으로 그린다 · 티켓 S15P21E102-318.
   *
   * 이전 판은 여기에 `PREPARING` 을 그렸다. 확정 디자인의 카드가 소속(`SSAFY 12기 ·
   * 백엔드`)과 연결 상세를 함께 요구했는데 그 값을 주는 조회가 없었기 때문이다. 그런데
   * SSAFY 로그인은 MVP 에서 쓰지 않기로 했고, 결과적으로 GitHub 으로 정상 로그인한
   * 사람이 자기 계정 화면에서 "계정 정보를 아직 불러올 수 없어요"를 봤다.
   *
   * `useMe` 는 헤더가 이미 구독하고 있어 여기서 부른다고 요청이 늘지 않는다. 주는 값은
   * `displayName`·`avatarUrl`·`githubConnected`·`role` 넷이고 그 넷만 그린다.
   *
   * GitHub 핸들을 따로 적지 않는 이유는 `/auth/me` 에 그 필드가 없기 때문이다 —
   * `displayName` 자체가 프로필 이름이 없을 때 핸들로 접힌 값이라(`MeResponse` 주석),
   * 이름과 핸들을 두 줄로 나누면 같은 값이 두 번 보이거나 없는 값을 지어내게 된다.
   */
  const { data: me } = useMe()

  /*
   * 분석 설정 · 목표 직무는 `GET /me/target`, 저장소 수는 `GET /me/technologies` 다.
   *
   * 저장소 쪽이 **선택**이 아니라 **분석** 기준인 것에 유의한다. 현재 선택 개수를 주는
   * 조회는 없고(`GET /me/repositories/selection` 은 BE 에 매핑이 없다), 있는 것은 저장소별
   * 최신 완료 분석을 센 `summary.repositoryCount` 다. 그래서 문구도 `분석한 저장소`다 —
   * Evidence 개요가 같은 값을 부르는 이름과 맞췄다.
   *
   * 훅은 Evidence 화면이 쓰는 것을 그대로 쓴다. 같은 키라 캐시를 공유해 조회가 늘지 않는다.
   */
  const targetQuery = useTarget()
  const profileQuery = useTechnologyProfile()
  const settings = analysisSettingsRows({
    targetRoleLabel:
      normalizeTargetRole(targetQuery.data?.targetRole) === null
        ? null
        : targetRoleDisplayName(targetQuery.data?.targetRole),
    analyzedRepositoryCount: profileQuery.data?.summary.repositoryCount ?? null,
  })

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
        <PageHero title="내 정보" />
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
          {/*
            ACCOUNT · 인증이 아는 것만 그린다.

            `min-w-0` 이 없으면 긴 이름에서 가로 스크롤이 생긴다. 이 카드는 grid item 이라
            기본 `min-width: auto` 로 내용보다 작아지지 않고, 그러면 안쪽 `truncate` 가
            잘라 낼 폭을 못 받는다(2026-09-18 390px 확인). 아바타가 없으면 이름 첫 글자로 대신한다
            (`UserMenu` 와 같은 규칙) — 가짜 GitHub 아바타를 만들지 않는다.
          */}
          <section className="min-w-0 rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">ACCOUNT</p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              내 GitHub 계정
            </h2>

            {me === undefined ? (
              /*
                확인 중. 카드 골격을 유지한 채 자리만 비운다 — 여기서 상태 카드를 그리면
                새로고침마다 계정 화면이 한 번씩 "없음"을 주장한다.
              */
              <div className="mt-4 flex items-center gap-3.5" aria-busy="true">
                <span className="size-11 shrink-0 animate-pulse rounded-full bg-[#EEF2F8]" />
                <span className="h-4 w-28 animate-pulse rounded bg-[#EEF2F8]" />
              </div>
            ) : me === null ? (
              // 가드가 이미 로그인 화면으로 보내므로 사실상 지나가지 않는 갈래다.
              <p className="mt-4 text-[13px] text-brand-faint">로그인이 필요합니다.</p>
            ) : (
              <div className="mt-4 flex items-center gap-3.5">
                {me.avatarUrl === null ? (
                  <span
                    aria-hidden
                    className="grid size-11 shrink-0 place-items-center rounded-full bg-tone-accent-bg text-[16px] font-extrabold text-brand-600"
                  >
                    {accountName(me.displayName).charAt(0).toUpperCase()}
                  </span>
                ) : (
                  <img
                    src={me.avatarUrl}
                    alt=""
                    className="size-11 shrink-0 rounded-full object-cover"
                    style={{ border: '1px solid rgba(0, 0, 0, 0.06)' }}
                  />
                )}
                {/* `min-w-0` 이 없으면 긴 이름이 카드를 밀어 넓힌다. */}
                <div className="min-w-0">
                  <p className="truncate text-[16px] font-[750] tracking-[-0.02em] text-brand-ink">
                    {accountName(me.displayName)}
                  </p>
                  {/* 연결 여부는 실제 값이 참일 때만 말한다. */}
                  {me.githubConnected && (
                    <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-brand-muted">
                      <span aria-hidden className="size-1.5 rounded-full bg-tone-success" />
                      GitHub 연결됨
                    </p>
                  )}
                </div>
              </div>
            )}
          </section>

          {/*
            ANALYSIS SETTINGS · 무엇을 기준으로 분석하고 비교하는지.

            상단 `GitHub 다시 분석` 과 뜻이 겹치지 않게 둔다 — 저장소는 **분석 대상**을,
            목표 직무는 **공고 비교 기준**을 바꾸고, 재분석은 지금 대상을 다시 읽는다.
          */}
          <section className="min-w-0 rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
              ANALYSIS SETTINGS
            </p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              분석 설정
            </h2>

            <dl className="mt-4 grid gap-2">
              {[
                { term: '저장소', value: settings.repository },
                { term: '목표 직무', value: settings.targetRole },
              ].map((row) => (
                <div
                  key={row.term}
                  className="flex items-baseline justify-between gap-3 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3"
                >
                  <dt className="shrink-0 text-[12.5px] text-brand-muted">{row.term}</dt>
                  {/* 값이 길어도 라벨을 밀지 않는다. */}
                  <dd className="min-w-0 truncate text-[13px] font-[750] text-brand-ink">
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>

            {/*
              카드 폭이 372px 이라 두 버튼을 한 줄에 두면 글자가 접힌다. 세로로 쌓고
              둘 다 전체 폭을 쓴다. 목적지는 기존 화면 그대로다 — 새 라우트를 만들지 않는다.
            */}
            <div className="mt-4 grid gap-2">
              <Link
                to="/onboarding/repositories"
                className="block rounded-xl border border-brand-line bg-white px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
              >
                저장소 다시 선택
              </Link>
              <Link
                to="/roles"
                className="block rounded-xl border border-brand-line bg-white px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
              >
                목표 직무 변경
              </Link>
            </div>
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
                  최근 분석
                </p>
                <h2 className="mt-2.5 text-[19px] font-[800] tracking-[-0.02em] text-brand-ink">
                  {historyQuery.isPending
                    ? '최근 분석을 불러오는 중이에요'
                    : '아직 분석한 적이 없어요'}
                </h2>
                <p className="mt-2 max-w-[420px] text-[13px] leading-[1.7] text-brand-muted">
                  {historyQuery.isPending
                    ? '잠시만 기다려 주세요.'
                    : '저장소를 선택하면 기술 사용 근거를 찾습니다.'}
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
                    최근 분석
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
                      {HISTORY_STATUS_LABEL[latest.status]}
                    </span>
                  </div>

                  <dl className="mt-3.5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px]">
                    <div className="flex items-center gap-1.5">
                      <dt className="text-brand-faint">저장소</dt>
                      <dd className="font-evidence font-[750] text-brand-ink-soft">
                        {latest.repositories || '이름 기록 없음'}
                      </dd>
                    </div>
                    <span aria-hidden className="h-3 w-px bg-brand-line" />
                    <div className="flex items-center gap-1.5">
                      <dt className="text-brand-faint">결과</dt>
                      <dd className="font-[750] text-brand-ink-soft">
                        {userFacingText(latest.resultText)}
                      </dd>
                    </div>
                  </dl>
                </div>

                {/* 버튼은 카드 안 오른쪽이다. 아래로 내리면 카드가 두 배로 길어진다. */}
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <Link
                    to="/evidence"
                    className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-4 py-2.5 text-[13px] font-[750] text-white shadow-[0_10px_22px_rgba(47,94,235,0.26)]"
                  >
                    내 기술 보기
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
            <DataRegion title="분석 이력">
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
                      <p className="truncate text-[12.5px] text-brand-muted">
                        {userFacingText(item.resultText)}
                      </p>
                      <span
                        className={`w-fit justify-self-start rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-[0.06em] lg:justify-self-end ${
                          HISTORY_STATUS_CLASS[item.status]
                        }`}
                      >
                        {HISTORY_STATUS_LABEL[item.status]}
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

    </div>
  )
}
