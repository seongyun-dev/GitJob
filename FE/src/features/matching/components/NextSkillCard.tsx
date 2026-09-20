import { Link } from 'react-router'
import type { NextSkillEvidenceStatus, NextSkillView } from '@/features/matching/model/view'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'

/**
 * 다음 학습 기술 카드 · 화면 10 Recommendation.
 *
 * **증가분을 화면에서 만들지 않는다(S15P21E102-279).** 이전에는 `확보 후 - 현재`로
 * 뺐는데, 이제 서버가 `increasedCount`를 준다. 뺄셈을 남겨 두면 세 값 중 하나가
 * 다른 계산에서 왔을 때 그 불일치가 화면에서 감춰진다.
 *
 * **목표 Level을 표시하지 않는다.** C가 후보별 목표 Level을 주지 않기 때문이고,
 * `L2` 같은 값을 화면이 정하면 없는 요구를 만들어 낸다(계약 §6-3).
 *
 * <h2>무엇이 가장 먼저 읽혀야 하는가 (S15P21E102-364)</h2>
 *
 * 정렬 기준이 공고 수 증가분 하나이므로 카드에서 가장 큰 활자도 `increasedCount`다.
 * 이전에는 `현재 3` · `+2` · `확보 후 5`가 한 줄에 세 덩어리로 흩어져 있어 무엇이
 * 순위를 정한 값인지 읽히지 않았다. 지금은 증가분이 먼저 서고 `3개 → 5개`가 그 옆에서
 * 가정을 설명한다.
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
  const { currentFullMatch, projectedFullMatch, increasedCount } = skill
  const hasCounts =
    currentFullMatch !== null && projectedFullMatch !== null && increasedCount !== null

  /*
   * 근거는 앞의 두 문장만 편다. C가 주는 문장은 수요 · What-if · 선행 · Evidence
   * 순서라 앞의 둘이 "얼마나 요구되는가"와 "얼마나 늘어나는가"를 이미 말한다. 나머지를
   * 지우지는 않는다 — 같은 데이터를 접었을 뿐이고, 세 카드가 모두 같은 규칙을 쓴다.
   * 1순위만 전부 펴고 나머지는 한 줄만 주던 이전 방식이 카드 높이를 벌려 놓았다.
   */
  const leadReasons = skill.reasons.slice(0, 2)
  const restReasons = skill.reasons.slice(2)

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

      {/* 필수 전체 충족 공고의 변화. 증가분이 먼저 서고 가정이 그 옆에 붙는다. */}
      <div className="mt-4">
        <p className="text-[11.5px] font-semibold text-brand-faint">필수 충족 공고</p>
        {!hasCounts ? (
          <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-muted">
            공고 변화를 집계하고 있습니다.
          </p>
        ) : (
          <>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <p
                className={`font-[850] tracking-[-0.05em] ${
                  emphasis ? 'text-[54px] text-brand-600' : 'text-[42px] text-brand-ink-soft'
                } leading-none`}
              >
                +{increasedCount}
              </p>
              <p className="text-[15px] font-[750] tracking-[-0.02em] text-brand-muted">
                {currentFullMatch}개
                <span aria-hidden className="mx-1.5 text-brand-faint">
                  →
                </span>
                <span className="text-[17px] font-[850] text-brand-ink">{projectedFullMatch}개</span>
              </p>
            </div>
            {/*
              두 칸 막대. 현재분과 새로 충족되는 분을 이어 붙여 "늘어나는 만큼"을
              길이로 보여준다. 길이의 뜻은 바로 아래 줄이 글로 받는다.
            */}
            <div className="mt-3 flex gap-1">
              <div style={{ flex: Math.max(currentFullMatch, 1) }}>
                <MeterBar
                  value={currentFullMatch}
                  total={currentFullMatch}
                  tone="muted"
                  height={8}
                />
              </div>
              <div style={{ flex: Math.max(increasedCount, 1) }}>
                <MeterBar value={increasedCount} total={increasedCount} height={8} />
              </div>
            </div>
            <p className="mt-2 text-[11.5px] text-brand-faint">
              현재 충족 {currentFullMatch}건 · 새로 충족 {increasedCount}건
            </p>
          </>
        )}
      </div>

      <p className="mt-5 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">추천 이유</p>
      {skill.reasons.length === 0 ? (
        <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-faint">
          근거 문장이 아직 준비되지 않았습니다.
        </p>
      ) : (
        <>
          <ul className="mt-2 grid gap-1.5">
            {leadReasons.map((reason) => (
              <li key={reason} className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted">
                <span aria-hidden className="text-brand-600">
                  ·
                </span>
                {reason}
              </li>
            ))}
          </ul>
          {restReasons.length > 0 && (
            <details className="mt-2 text-[12px] text-brand-muted">
              <summary className="w-fit cursor-pointer font-semibold hover:text-brand-ink">
                근거 {restReasons.length}개 더 보기
              </summary>
              <ul className="mt-2 grid gap-1.5">
                {restReasons.map((reason) => (
                  <li
                    key={reason}
                    className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted"
                  >
                    <span aria-hidden className="text-brand-600">
                      ·
                    </span>
                    {reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {/*
        What-if 화면으로 넘긴다. 어느 기술을 볼지가 쿼리로 실려야 두 화면이
        같은 후보를 가리킨다.
      */}
      <Link
        to={`/what-if?tech=${skill.techId}`}
        onClick={onSelect}
        className={`mt-5 block rounded-xl px-4 py-3 text-center text-[13.5px] font-[750] ${
          emphasis
            ? 'gj-clickable-primary bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]'
            : 'gj-clickable border border-brand-line bg-white text-brand-ink'
        }`}
      >
        {increasedCount === null ? '새로 충족되는 공고 보기' : `새로 충족 ${increasedCount}개 보기`}
      </Link>
    </section>
  )
}
