import { Link } from 'react-router'
import type { NextSkillView } from '@/features/matching/model/view'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'

/**
 * 다음 학습 기술 카드 · 화면 10 Recommendation.
 *
 * 확정 디자인 `Final v2`는 1순위를 크게, 후순위를 작게 둔다(실측 `463 · 370 · 370`).
 * 크기 차이가 곧 정렬 기준의 표현이라 `emphasis`로 구분한다.
 *
 * **증가분을 화면에서 만들지 않는다(S15P21E102-279).** 이전에는 `확보 후 - 현재`로
 * 뺐는데, 이제 서버가 `increasedCount`를 준다. 뺄셈을 남겨 두면 세 값 중 하나가
 * 다른 계산에서 왔을 때 그 불일치가 화면에서 감춰진다.
 *
 * **목표 Level을 표시하지 않는다.** C가 후보별 목표 Level을 주지 않기 때문이고,
 * `L2` 같은 값을 화면이 정하면 없는 요구를 만들어 낸다(계약 §6-3).
 */
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

  return (
    <section
      className={
        emphasis
          ? 'rounded-[24px] border border-brand-line-active bg-[linear-gradient(160deg,#FFFFFF,#F7FAFF_62%,#F1F6FF)] p-7 shadow-[0_22px_60px_rgba(56,103,195,0.14)]'
          : 'rounded-[24px] border border-brand-line bg-white p-6 shadow-[0_10px_28px_rgba(25,47,81,0.07)]'
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-extrabold tracking-[0.14em] text-brand-600">
          {skill.rank}순위
        </p>
        <div className="flex items-center gap-1.5">
          {/*
            판정되지 않은 Level을 L0으로 채우지 않는다. 미판정과 "선언만 확인"은
            다른 상태이고, LevelBadge는 L0을 후자로 그린다.
          */}
          {skill.fromLevel === null ? (
            <span className="rounded-lg border border-brand-line bg-white px-2 py-1 text-[11.5px] font-[750] text-brand-faint">
              분석 전
            </span>
          ) : (
            <LevelBadge level={skill.fromLevel} />
          )}
        </div>
      </div>

      <h2
        className={`mt-3 font-[750] tracking-[-0.03em] text-brand-ink ${
          emphasis ? 'text-[26px] leading-[1.2]' : 'text-[19px] leading-[1.25]'
        }`}
      >
        {skill.techName}
      </h2>

      {/* 필수 전체 충족 공고의 변화. 현재와 확보 후를 나란히 둬야 가정이 읽힌다 */}
      <div className="mt-5">
        <p className="text-[11.5px] text-brand-faint">필수 기술을 모두 충족하는 공고</p>
        {!hasCounts ? (
          <p className="mt-2 text-[12.5px] leading-[1.6] text-brand-muted">
            공고 변화를 집계하고 있습니다.
          </p>
        ) : (
          <>
            <div className="mt-2 flex items-end gap-4">
              <div>
                <p className="text-[11px] text-brand-faint">현재</p>
                <p className="text-[20px] leading-none font-[850] tracking-[-0.04em] text-brand-ink-soft">
                  {currentFullMatch}
                </p>
              </div>
              <p
                className={`font-[850] tracking-[-0.05em] ${
                  emphasis ? 'text-[52px] text-brand-600' : 'text-[40px] text-brand-ink-soft'
                } leading-none`}
              >
                +{increasedCount}
              </p>
              <div>
                <p className="text-[11px] text-brand-faint">확보 후</p>
                <p className="text-[20px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                  {projectedFullMatch}
                </p>
              </div>
            </div>
            {/*
              두 칸 막대. 현재분과 새로 충족되는 분을 이어 붙여 "늘어나는 만큼"을
              길이로 보여준다.
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
        <ul className="mt-2 grid gap-1.5">
          {(emphasis ? skill.reasons : skill.reasons.slice(0, 1)).map((reason) => (
            <li key={reason} className="flex gap-2 text-[12.5px] leading-[1.6] text-brand-muted">
              <span aria-hidden className="text-brand-600">
                ·
              </span>
              {reason}
            </li>
          ))}
        </ul>
      )}

      {/*
        What-if 화면으로 넘긴다. 어느 기술을 볼지가 쿼리로 실려야 두 화면이
        같은 후보를 가리킨다.
      */}
      <Link
        to={`/what-if?tech=${skill.techId}`}
        onClick={onSelect}
        className={`mt-6 block rounded-xl px-4 py-3.5 text-center text-[13.5px] font-[750] ${
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
