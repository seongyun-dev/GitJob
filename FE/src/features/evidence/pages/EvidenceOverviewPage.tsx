import { useState } from 'react'
import { Link } from 'react-router'
import {
  AnalysisContextPanel,
  ReinforcementPanel,
} from '@/features/evidence/components/EvidenceSidePanels'
import { EvidenceTable } from '@/features/evidence/components/EvidenceTable'
import { TechnologySummaryCard } from '@/features/evidence/components/TechnologySummaryCard'
import type {
  AnalyzedRepository,
  TechnologyVerdict,
} from '@/features/evidence/api/technologiesApi'
import {
  profileErrorMessage,
  useTechnologyProfile,
} from '@/features/evidence/hooks/useTechnologyProfile'
import { LEVEL_STEPS } from '@/shared/constants/evidenceLevel'
import { EvidenceLevel } from '@/shared/ui/EvidenceLevel'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { LevelLegend } from '@/shared/ui/LevelBadge'
import { Modal } from '@/shared/ui/Modal'
import { StatStrip } from '@/shared/ui/StatStrip'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 기술 Evidence 결과 · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `08 My Evidence`).
 *
 * v2 구조: hero(+우측 CTA 2개) → 지표 4연 스트립 → `956/372` split
 * (기술별 판정 표 | 근거 보강 필요 + ANALYSIS CONTEXT) → 각주.
 *
 * 기술 목록은 `GET /me/technologies`에서 읽는다. Level 판정은 BE가 하고 FE는
 * 계산하지 않는다.
 *
 * PERSONAL 은 본인이 쓴 근거만으로 같은 규칙을 다시 판정한 값이라 언제나
 * REPOSITORY 이하다. 둘의 차이가 "저장소에는 있으나 본인 기여가 확인되지 않았다"를
 * 뜻한다.
 *
 * null 은 "본인이 안 썼다"가 아니라 확인되지 않았다는 뜻이다 -- 기여 판정을 끄고
 * 돌린 분석이거나, 얕은 체크아웃이거나, GitHub 이 커밋을 계정과 연결하지 못한
 * 경우다. 그래서 "미판정"으로 쓰고 L0 로 표시하지 않는다.
 *
 * v2 hero 우측의 `분석 완료 | 분석 전` 세그먼트는 아트보드에서 상태를 바꿔 보기
 * 위한 디자인 도구 장치라 옮기지 않는다. 그 옆 CTA 두 개는 실제 이동이라 남긴다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-137(이윤서)에 있다. 시각 적용까지만 한다.
 */

/**
 * 지표에서 열리는 목록 세 가지. 네 번째 지표(마지막 분석)는 무언가를 센 값이 아니라
 * 시각 하나라 열 목록이 없다.
 */
type StatDetail = 'technologies' | 'advanced' | 'repositories'

/**
 * v2가 hero 아래에 두는 네 지표. 이름과 기준은 제품 정의라 지금 보여줄 수 있고,
 * 값은 Evidence 결과 목록 API가 준다(S15P21E102-134 미착수).
 */
export function EvidenceOverviewPage() {
  const profile = useTechnologyProfile()
  const summary = profile.data?.summary
  const technologies = profile.data?.technologies ?? []
  const repositories = profile.data?.repositories ?? []
  const analyzedNothing = repositories.length === 0

  /** 어느 지표의 목록이 열려 있는지. 한 번에 하나만 연다. */
  const [openDetail, setOpenDetail] = useState<StatDetail | null>(null)

  /**
   * "L2 이상"이 센 대상.
   *
   * 판정은 BE 몫이고 FE는 Level을 만들지 않는다. 여기서 하는 것은 이미 받은 Level로
   * **거르는 것**뿐이라 판정을 다시 하는 게 아니다. 기준 열은 지표 caption과 같은
   * Repository Level이다.
   */
  const advanced = technologies.filter(
    (technology) => LEVEL_STEPS[technology.repositoryLevel] >= LEVEL_STEPS.L2,
  )

  /**
   * v2 가 hero 아래에 두는 네 지표.
   *
   * 값이 없을 때 `0`이나 `-`로 채우지 않는다. `0`은 "분석했더니 없었다"는 거짓이
   * 되고 `-`는 무엇을 기다리는지 알려주지 않는다. `StatStrip`이 note 문자열만
   * 받으므로 수치도 문자열로 넣는다.
   *
   * 앞의 세 개는 **무언가를 센 값**이라 그 대상 목록을 열 수 있다. 셀 대상이 아직
   * 없으면(분석 전이거나 0개) `onOpen`을 넘기지 않는다 -- 눌러도 빈 목록만 나오는
   * 버튼은 "볼 게 있다"는 거짓말이 된다.
   */
  const stats = [
    {
      label: '확인된 기술',
      note: summary === undefined ? '분석 후 표시' : `${summary.technologyCount}개`,
      caption: 'Repository Level 기준',
      onOpen: technologies.length > 0 ? () => setOpenDetail('technologies') : undefined,
    },
    {
      label: 'L2 이상',
      note: summary === undefined ? '분석 후 표시' : `${summary.advancedCount}개`,
      caption: '코드에서 실제로 다룬 기술',
      onOpen: advanced.length > 0 ? () => setOpenDetail('advanced') : undefined,
    },
    {
      label: '분석한 Repository',
      note: summary === undefined ? '분석 후 표시' : `${summary.repositoryCount}개`,
      caption: '저장소별 최신 분석 기준',
      onOpen: repositories.length > 0 ? () => setOpenDetail('repositories') : undefined,
    },
    {
      label: '마지막 분석',
      note:
        summary?.analyzedAt == null ? '기록 없음' : formatDateTime(summary.analyzedAt),
      caption: '가장 최근 성공한 분석',
    },
  ] as const
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="MY EVIDENCE"
          title="내 GitHub에서 확인된 기술"
          description="Evidence는 점수가 아니라 근거입니다. Personal은 본인 Commit으로 확인된 범위, Repository는 저장소 전체 기준입니다."
        />
        <div className="flex shrink-0 flex-wrap gap-2.5">
          <Link
            to="/onboarding/repositories"
            className="rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            GitHub 다시 분석
          </Link>
          <Link
            to="/roles"
            className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
          >
            직무 선택하고 공고 비교
          </Link>
        </div>
      </div>

      <div className="mt-7">
        <StatStrip items={stats} />
      </div>

      <div className="gj-split mt-4">
        <EvidenceTable>
          <TechnologyRows
            loading={profile.isPending}
            error={profile.isError ? profileErrorMessage(profile.error) : null}
            analyzedNothing={analyzedNothing}
            technologies={technologies}
          />
        </EvidenceTable>

        <div className="grid gap-4">
          <ReinforcementPanel />
          <AnalysisContextPanel />
        </div>
      </div>

      {/*
        Level 범례. 척도가 네 단계라는 것은 제품 정의라 판정 결과가 없어도 보여준다.
        단계별 의미는 등급 정책 확정 후 constants에서 채워진다.
      */}
      <div className="mt-5">
        <LevelLegend />
      </div>

      <PageFootnote>
        Personal Level이 Repository Level보다 낮은 기술은 저장소에는 구현이 있으나 본인 기여
        근거가 확인되지 않은 경우입니다. 점수로 환산하지 않습니다.
      </PageFootnote>

      {openDetail !== null && (
        <StatDetailModal
          detail={openDetail}
          technologies={technologies}
          advanced={advanced}
          repositories={repositories}
          onClose={() => setOpenDetail(null)}
        />
      )}
    </div>
  )
}

/**
 * 지표가 센 대상을 그대로 펼쳐 보이는 모달.
 *
 * 지표는 숫자 하나라 "무엇이 그렇게 세어졌는지"를 말하지 못한다. 10개가 어떤 10개인지
 * 모르면 그 숫자를 근거로 쓸 수 없다. 여는 목록은 지표 caption과 **같은 기준**이라야
 * 한다 -- 다른 기준의 목록을 보여주면 숫자와 목록이 어긋난다.
 */
function StatDetailModal({
  detail,
  technologies,
  advanced,
  repositories,
  onClose,
}: {
  detail: StatDetail
  technologies: readonly TechnologyVerdict[]
  advanced: readonly TechnologyVerdict[]
  repositories: readonly AnalyzedRepository[]
  onClose: () => void
}) {
  if (detail === 'repositories') {
    return (
      <Modal
        title="분석한 Repository"
        description="저장소별 최신 분석 기준입니다. 판정은 아래 커밋 시점의 코드에서 나왔습니다."
        onClose={onClose}
      >
        <ul className="grid gap-2">
          {repositories.map((repository) => (
            <li
              key={repository.repositoryId}
              className="rounded-[14px] border border-brand-line px-4 py-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                {/* V12 이전 분석은 이름을 안 남겼다. 그때는 이름 자리를 비워 두지 않고 말한다. */}
                <p className="truncate text-[13px] font-[750] text-brand-ink">
                  {repository.fullName ?? '이름이 기록되지 않은 저장소'}
                </p>
                <p className="shrink-0 text-[11.5px] text-brand-faint">
                  근거 {repository.evidenceCount.toLocaleString('ko-KR')}건
                </p>
              </div>
              <p className="mt-1 text-[11.5px] text-brand-muted">
                <span className="font-mono">{repository.commitSha.slice(0, 7)}</span> ·{' '}
                {formatDateTime(repository.analyzedAt)}
              </p>
            </li>
          ))}
        </ul>
      </Modal>
    )
  }

  const isAdvanced = detail === 'advanced'
  const items = isAdvanced ? advanced : technologies

  return (
    <Modal
      title={isAdvanced ? 'L2 이상인 기술' : '확인된 기술'}
      description={
        isAdvanced
          ? '코드에서 실제로 다룬 기술입니다. Repository Level이 L2 이상인 것만 모았습니다.'
          : 'Repository Level 기준으로 근거가 확인된 기술 전부입니다.'
      }
      onClose={onClose}
    >
      <ul className="grid gap-2">
        {items.map((technology) => (
          <li
            key={technology.techId}
            className="flex items-center gap-3 rounded-[14px] border border-brand-line px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-[750] text-brand-ink">
                {technology.displayName}
              </p>
              <p className="mt-0.5 truncate text-[11.5px] text-brand-muted">
                근거 {technology.evidenceCount.toLocaleString('ko-KR')}건 · 저장소{' '}
                {technology.repositoryCount}개
              </p>
            </div>
            <span className="shrink-0">
              <EvidenceLevel level={technology.repositoryLevel} />
            </span>
            <Link
              to={`/evidence/${technology.techId}`}
              onClick={onClose}
              className="shrink-0 text-[12.5px] text-tone-accent underline"
            >
              보기
            </Link>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

/**
 * 표 본문.
 *
 * 빈 상태가 둘이라 구분한다. 분석한 적이 없는 것과, 분석했는데 Registry 가 아는
 * 기술이 하나도 안 나온 것은 사용자가 해야 할 일이 다르다.
 */
function TechnologyRows({
  loading,
  error,
  analyzedNothing,
  technologies,
}: {
  loading: boolean
  error: string | null
  analyzedNothing: boolean
  technologies: TechnologyVerdict[]
}) {
  /**
   * 요약을 펼친 기술 하나. 여러 개를 동시에 열 수 있게 하지 않는다 -- 그 순간
   * 마운트할 때 전부 부르는 것과 같아지고, GPU 자리가 둘뿐이라 대부분이 대기로
   * 떨어진다.
   */
  const [openSummary, setOpenSummary] = useState<string | null>(null)

  if (loading) {
    return <StateCard kind="LOADING" title="불러오는 중" description="판정 결과를 읽고 있습니다." />
  }
  if (error !== null) {
    return <StateCard kind="ERROR" title="판정 결과를 불러오지 못했어요" description={error} />
  }
  if (analyzedNothing) {
    return (
      <StateCard
        kind="NO_DATA"
        title="아직 분석한 저장소가 없어요"
        description="저장소를 선택해 분석하면 여기에 기술별 판정이 쌓입니다."
        action={
          <Link to="/onboarding/repositories" className="text-tone-accent underline">
            저장소 선택하기
          </Link>
        }
      />
    )
  }
  if (technologies.length === 0) {
    return (
      <StateCard
        kind="INSUFFICIENT_DATA"
        title="판정할 수 있는 기술이 없었어요"
        description="분석은 끝났지만 Registry가 아는 기술이 저장소에서 확인되지 않았습니다."
      />
    )
  }

  return (
    <ul className="px-[22px] py-2">
      {technologies.map((technology) => (
        <TechnologyRow
          key={technology.techId}
          technology={technology}
          open={openSummary === technology.techId}
          onToggle={() =>
            setOpenSummary((current) =>
              current === technology.techId ? null : technology.techId,
            )
          }
        />
      ))}
    </ul>
  )
}

/**
 * 표의 한 행. 펼치면 그 기술의 AI 요약을 부른다.
 *
 * <h2>왜 마운트할 때 부르지 않는가</h2>
 *
 * 요약 생성은 노트북 GPU 한 대에서 돌고 BE 가 동시 2건까지만 보낸다. 행 열 개가
 * 뜨자마자 각자 부르면 여덟 개가 즉시 `PENDING` 으로 떨어지고, 5초마다 재시도가
 * 돌면서 첫 화면이 한참 출렁인다. 캐시가 빈 첫 사용자가 정확히 그 경우다.
 *
 * 그래서 사용자가 "이 기술을 보겠다"고 말할 때만 켠다. 한 번에 하나만 열리므로
 * 진행 중인 요청도 언제나 하나다.
 */
function TechnologyRow({
  technology,
  open,
  onToggle,
}: {
  technology: TechnologyVerdict
  open: boolean
  onToggle: () => void
}) {
  return (
    <li className="border-b border-brand-line py-3 last:border-b-0">
      <div className="grid items-center gap-[18px] lg:grid-cols-[minmax(0,206fr)_150px_110px_minmax(0,319fr)_44px]">
        {/*
          기술명 자리를 버튼으로 쓴다. 열을 하나 더 만들면 확정 디자인의 다섯 열
          비율이 흐트러지고, 행 전체를 누르게 하면 오른쪽 `보기` 링크와 눌리는
          자리가 겹친다.
        */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 items-center gap-1.5 text-left"
        >
          <span aria-hidden className="shrink-0 text-[10px] text-brand-faint">
            {open ? '▾' : '▸'}
          </span>
          <span className="truncate text-[14px] font-semibold text-brand-ink">
            {technology.displayName}
          </span>
        </button>

        {technology.personalLevel === null ? (
          <span className="text-[12.5px] text-brand-faint">미판정</span>
        ) : (
          <EvidenceLevel level={technology.personalLevel} />
        )}

        <span>
          <EvidenceLevel level={technology.repositoryLevel} />
        </span>

        <span className="truncate text-[12.5px] text-brand-faint">
          근거 {technology.evidenceCount.toLocaleString('ko-KR')}건 · 저장소{' '}
          {technology.repositoryCount}개
        </span>

        <Link
          to={`/evidence/${technology.techId}`}
          className="text-right text-[12.5px] text-tone-accent underline"
        >
          보기
        </Link>
      </div>

      {open && (
        <div className="mt-3">
          <TechnologySummaryCard techId={technology.techId} variant="inline" />
        </div>
      )}
    </li>
  )
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
