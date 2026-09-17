import { Link, useParams } from 'react-router'
import type { EvidenceLevelGroup } from '@/features/evidence/api/technologiesApi'
import { EvidenceLevelGroups } from '@/features/evidence/components/EvidenceLevelGroups'
import { TechnologySummaryCard } from '@/features/evidence/components/TechnologySummaryCard'
import {
  profileErrorMessage,
  useTechnologyEvidence,
} from '@/features/evidence/hooks/useTechnologyProfile'
import { technologyDisplayName } from '@/shared/presentation/userFacingLabels'
import { EvidenceLevel } from '@/shared/ui/EvidenceLevel'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 상세 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `09 Evidence Detail`).
 *
 * v2 구조: 목록 복귀 링크 → hero → Level 2칸(Personal / Repository) →
 * `956/372` split(근거 표 | 다음 Level 안내) → 각주.
 *
 * 근거 표는 v2의 다섯 열을 그대로 쓴다.
 *   유형 / 파일 · 위치 / LEVEL 기여 / 기여자 / GitHub 이동  (52 · 436 · 150 · 130 · 70)
 *
 * v2는 표를 두 그룹으로 나눈다. `Personal Level에 반영된 Evidence`와
 * `Repository Level에만 반영된 Evidence`(타인 Commit → Personal 미반영)다.
 * 이 구분이 이 화면의 핵심이라 그룹 자리를 남기되, 몇 건인지는 API가 준다.
 *
 * 특정 기술의 판정 기준(예: Producer 구현 여부)은 기술마다 달라 하드코딩하지 않는다.
 * `techId`는 실제 route state지만 그것만으로 기술명을 만들 수 없어 제목에 쓰지 않는다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-138(이윤서)에 있다. 시각 적용까지만 한다.
 */
export function EvidenceDetailPage() {
  const { techId } = useParams()
  const evidence = useTechnologyEvidence(techId)
  const levels = evidence.data?.levels ?? []

  return (
    <div>
      <Link
        to="/evidence"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 내 기술 목록
      </Link>

      <div className="mt-3">
        <PageHero title={`${technologyDisplayName(techId ?? '')} 사용 근거`} />
      </div>

      <div className="mt-6 max-w-[320px] rounded-[14px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        <p className="text-[12px] font-semibold text-brand-muted">확인된 수준</p>
        <div className="mt-2">
          {evidence.data?.level === null || evidence.data?.level === undefined ? (
            <p className="text-[14px] font-[750] text-brand-faint">근거 없음</p>
          ) : (
            <EvidenceLevel level={evidence.data.level} />
          )}
        </div>
      </div>

      <div className="mt-4">
        <TechnologySummaryCard techId={techId} />
      </div>

      <div className="mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          {/*
            컬럼 헤더를 뺐다 · 티켓 S15P21E102-252.

            `유형 · 파일·위치 · LEVEL 기여 · 기여자` 다섯 열을 알리는 줄이었는데, 본문이
            Level → 저장소 → 파일 로 접히는 구조가 되면서 **그런 열이 더는 없다.** 없는
            열을 가리키는 머리글은 안내가 아니라 오독의 원인이다. 각 값이 무엇인지는
            배지와 묶음 제목이 자기 자리에서 말한다.
          */}
          <div className="p-4">
            <LevelGroups
              loading={evidence.isPending}
              error={evidence.isError ? profileErrorMessage(evidence.error) : null}
              levels={levels}
            />
          </div>
        </div>
      </div>

      <Link
        to={techId === undefined ? '/recommendations' : `/technologies/${techId}`}
        className="mt-4 inline-flex rounded-xl border border-brand-line bg-white px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
      >
        이 기술 자세히 보기 →
      </Link>
    </div>
  )
}

/**
 * Level 로 묶은 근거.
 *
 * <p>평평하게 나열하면 Spring Security 하나가 82 행이 되고, 같은 파일의 연속된
 * import 세 줄이 세 행을 차지한다. 그 화면은 "왜 L2 인가"에 답하지 않는다.
 * Level → 파일 → 라인 순으로 좁혀 들어가야 사람이 답을 얻는다. 접는 일은 BE 가
 * 한다 -- Level 마다 따로 상한을 걸어야 낮은 Level 이 통째로 사라지지 않는다.</p>
 */
function LevelGroups({
  loading,
  error,
  levels,
}: {
  loading: boolean
  error: string | null
  levels: EvidenceLevelGroup[]
}) {
  if (loading) {
    return <StateCard kind="LOADING" title="불러오는 중" description="판정 근거를 읽고 있습니다." />
  }
  if (error !== null) {
    return <StateCard kind="ERROR" title="근거를 불러오지 못했어요" description={error} />
  }
  if (levels.length === 0) {
    return (
      <StateCard
        kind="INSUFFICIENT_DATA"
        title="이 기술의 근거가 아직 없어요"
        description="분석한 저장소에서 이 기술의 사용 근거를 찾지 못했습니다."
      />
    )
  }

  return <EvidenceLevelGroups levels={levels} />
}
