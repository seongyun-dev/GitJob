import { Link } from 'react-router'
import {
  AnalysisContextPanel,
  ReinforcementPanel,
} from '@/features/evidence/components/EvidenceSidePanels'
import { EvidenceTable } from '@/features/evidence/components/EvidenceTable'
import type { TechnologyVerdict } from '@/features/evidence/api/technologiesApi'
import {
  profileErrorMessage,
  useTechnologyProfile,
} from '@/features/evidence/hooks/useTechnologyProfile'
import { EvidenceLevel } from '@/shared/ui/EvidenceLevel'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { LevelLegend } from '@/shared/ui/LevelBadge'
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
 * v2가 hero 아래에 두는 네 지표. 이름과 기준은 제품 정의라 지금 보여줄 수 있고,
 * 값은 Evidence 결과 목록 API가 준다(S15P21E102-134 미착수).
 */
export function EvidenceOverviewPage() {
  const profile = useTechnologyProfile()
  const summary = profile.data?.summary
  const technologies = profile.data?.technologies ?? []
  const analyzedNothing = (profile.data?.repositories.length ?? 0) === 0

  /**
   * v2 가 hero 아래에 두는 네 지표.
   *
   * 값이 없을 때 `0`이나 `-`로 채우지 않는다. `0`은 "분석했더니 없었다"는 거짓이
   * 되고 `-`는 무엇을 기다리는지 알려주지 않는다. `StatStrip`이 note 문자열만
   * 받으므로 수치도 문자열로 넣는다.
   */
  const stats = [
    {
      label: '확인된 기술',
      note: summary === undefined ? '분석 후 표시' : `${summary.technologyCount}개`,
      caption: 'Repository Level 기준',
    },
    {
      label: 'L2 이상',
      note: summary === undefined ? '분석 후 표시' : `${summary.advancedCount}개`,
      caption: '코드에서 실제로 다룬 기술',
    },
    {
      label: '분석한 Repository',
      note: summary === undefined ? '분석 후 표시' : `${summary.repositoryCount}개`,
      caption: '저장소별 최신 분석 기준',
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
    </div>
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
        <li
          key={technology.techId}
          className="grid items-center gap-[18px] border-b border-brand-line py-3 last:border-b-0 lg:grid-cols-[minmax(0,206fr)_150px_110px_minmax(0,319fr)_44px]"
        >
          <span className="truncate text-[14px] font-semibold text-brand-ink">
            {technology.displayName}
          </span>

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
        </li>
      ))}
    </ul>
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
