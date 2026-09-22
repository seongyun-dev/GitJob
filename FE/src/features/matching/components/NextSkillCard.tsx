import { Link } from 'react-router'
import { ConditionImpactSummary } from '@/features/matching/components/ConditionImpactSummary'
import type { NextSkillEvidenceStatus, NextSkillView } from '@/features/matching/model/view'
import { LevelBadge } from '@/shared/ui/LevelBadge'

/**
 * 다음 학습 기술 카드 · 화면 10 Recommendation.
 *
 * **관련 공고 수를 화면에서 만들지 않는다.** 필수·우대·합집합 건수는 C가
 * 동일한 공고 ID 집합에서 계산한다. 화면에서 둘을 더하면 겹치는 공고를 중복 센다.
 *
 * **목표 Level을 표시하지 않는다.** C가 후보별 목표 Level을 주지 않기 때문이고,
 * `L2` 같은 값을 화면이 정하면 없는 요구를 만들어 낸다(계약 §6-3).
 *
 * <h2>무엇이 가장 먼저 읽혀야 하는가 (S15P21E102-364)</h2>
 *
 * 정렬 기준인 중복 제외 관련 공고 수가 가장 크게 보이고, 필수·우대 건수는
 * 바로 아래에 분리한다. 전체 충족이나 지원 가능을 뜻하지 않는다.
 *
 * `emphasis`는 1순위다. 크기 차이가 곧 정렬 기준의 표현이지만 그 차이를 카드 높이로
 * 주지는 않는다 — 높이는 `.gj-trio`의 `align-items: start` 아래에서 내용이 정한다.
 */

/**
 * Level이 없는 이유별 배지.
 *
 * 이전에는 `fromLevel === null`을 전부 `분석 전`으로 그렸다. 추천 계산이 이미 끝난
 * 화면에서 그 문구는 "이 추천이 아직 분석되지 않았다"로 읽히고, 무엇보다 **미보유와
 * 미판정을 한 문구로 합쳤다**(S15P21E102-364). 계약은 둘을 나눠 주고 있었다.
 *
 * `PERSONAL_LEVEL_UNKNOWN`은 저장소에서 관측됐거나 아직 평가되지 않아 개인 Level이
 * 없는 상태다. 미보유로도 L0으로도 쓰지 않는다.
 */
const EVIDENCE_BADGE: Readonly<Record<NextSkillEvidenceStatus, { label: string; title: string }>> =
  {
    NOT_HELD: {
      label: '미보유',
      title: '분석한 저장소에서 보유 근거를 찾지 못한 기술입니다.',
    },
    L0: {
      label: '선언만 확인',
      title: '의존성 선언만 확인되어 구현·참여 기준의 보유 기술에는 포함되지 않았습니다.',
    },
    PERSONAL_LEVEL_UNKNOWN: {
      label: '내 수준 미판정',
      title:
        '저장소에서 관측됐거나 아직 평가되지 않아 개인 수준이 정해지지 않았습니다. 보유하지 않았다는 뜻이 아닙니다.',
    },
  }

function EvidenceBadge({ skill }: { skill: NextSkillView }) {
  /*
   * 판정된 Level이 있으면 그 값이 가장 정확한 표시다. L0을 여기서 문구로 바꾸지 않는
   * 이유는 `LevelBadge`가 이미 L0을 그 자체로 그리기 때문이다.
   */
  if (skill.fromLevel !== null) {
    return <LevelBadge level={skill.fromLevel} />
  }

  // 계약에 없는 값이면 아무 상태도 주장하지 않는다. 기본값으로 미보유를 쓰지 않는다.
  if (skill.evidenceStatus === null) {
    return null
  }

  /*
   * 표에 없는 상태면 배지를 지운다. `toEvidenceStatus`가 이미 걸러 주므로 타입상
   * 일어나지 않지만, 그 계약이 어긋나는 날 화면 전체가 ErrorBoundary로 떨어지는 것과
   * 배지 하나가 비는 것의 차이가 크다. 값이 없다고 카드를 잃을 이유는 없다.
   */
  const badge = EVIDENCE_BADGE[skill.evidenceStatus] as
    | (typeof EVIDENCE_BADGE)[NextSkillEvidenceStatus]
    | undefined
  if (badge === undefined) {
    return null
  }

  return (
    <span
      title={badge.title}
      className="rounded-lg border border-brand-line bg-white px-2 py-1 text-[11.5px] font-[750] text-brand-faint"
    >
      {badge.label}
    </span>
  )
}

export function NextSkillCard({
  skill,
  emphasis = false,
  onSelect,
}: {
  skill: NextSkillView
  /** 1순위 카드. 배경과 숫자 크기가 달라진다. */
  emphasis?: boolean
  onSelect?: () => void
}) {
  const { requiredImpactCount, preferredImpactCount, affectedJobCount } = skill
  const hasCounts = requiredImpactCount !== null && preferredImpactCount !== null && affectedJobCount !== null

  return (
    <section
      className={
        emphasis
          ? 'rounded-[24px] border border-brand-line-active bg-[linear-gradient(160deg,#FFFFFF,#F7FAFF_62%,#F1F6FF)] p-6 shadow-[0_22px_60px_rgba(56,103,195,0.14)]'
          : 'rounded-[24px] border border-brand-line bg-white p-6 shadow-[0_10px_28px_rgba(25,47,81,0.07)]'
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
          {skill.rank}순위
        </p>
        <EvidenceBadge skill={skill} />
      </div>

      <h2
        className={`mt-2.5 font-[750] tracking-[-0.03em] text-brand-ink ${
          emphasis ? 'text-[25px] leading-[1.2]' : 'text-[21px] leading-[1.25]'
        }`}
      >
        {skill.techName}
      </h2>

      {/* 추천 기술이 필수·우대로 언급된 공고 수. 공고는 합집합에서 한 번만 센다. */}
      <div className="mt-4">
        {!hasCounts ? (
          <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-muted">
            공고를 불러오는 중
          </p>
        ) : (
          <ConditionImpactSummary
            affectedCount={affectedJobCount}
            requiredCount={requiredImpactCount}
            preferredCount={preferredImpactCount}
            emphasis={emphasis}
          />
        )}
      </div>

      {skill.reasons.length > 0 && (
        <details className="mt-5 text-[12px] text-brand-muted">
          <summary className="w-fit cursor-pointer font-semibold hover:text-brand-ink">추천 이유</summary>
          <ul className="mt-2 grid gap-1.5">
            {skill.reasons.map((reason) => (
              <li key={reason} className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted">
                <span aria-hidden className="text-brand-600">·</span>
                {reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {/*
        What-if 화면으로 넘긴다. 어느 기술을 볼지가 쿼리로 실려야 두 화면이
        같은 후보를 가리킨다.
      */}
      {affectedJobCount === null ? (
        <p className="mt-5 rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-faint">
          새 기준으로 다시 계산 중
        </p>
      ) : (
        <Link
          to={`/what-if?tech=${skill.techId}`}
          onClick={onSelect}
          className={`mt-5 block rounded-xl px-4 py-3 text-center text-[13.5px] font-[750] ${
            emphasis
              ? 'gj-clickable-primary bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]'
              : 'gj-clickable border border-brand-line bg-white text-brand-ink'
          }`}
        >
          공고 보기
        </Link>
      )}
    </section>
  )
}
