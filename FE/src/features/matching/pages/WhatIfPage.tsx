import { Link, useSearchParams } from 'react-router'
import { RequirementChipList } from '@/features/matching/components/RequirementChip'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { NEXT_SKILLS, WHAT_IF_DISCLAIMER } from '@/mocks/fixtures/nextSkill'
import type { NextSkillFixture } from '@/mocks/types'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * What-if · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `03 What-if`).
 *
 * v2 구조: hero → 후보 순위 칩 → `571 / 757` split(가정 카드 | NEWLY MATCHED) → 각주.
 *
 * What-if의 의미는 **"이 기술 Evidence가 목표 Level이 되었다고 가정할 때 기술요건이
 * 매칭되는 공고가 얼마나 늘어나는가"** 다. 합격 가능성 증가가 아니다.
 *
 * 증감을 화면에서 계산하지 않는다. `현재 12 → 확보 후 27` 같은 값은 C조가 같은
 * Snapshot에서 다시 대조해 돌려주는 결과이고, FE가 `after - before`로 만들어도 되는
 * 값이 아니다(PROJECT_GUIDE §2). 조회 API가 없어 지금은 디자인 fixture가 두 값을
 * 모두 갖는다.
 *
 * 어느 후보를 보는지는 **주소에 실린다**(`?tech=kafka`). 추천 화면에서 넘어온 링크가
 * 그 값을 담고 있고, 새로고침해도 같은 후보가 열려야 하며, 팀에 링크를 공유할 수도
 * 있어야 한다. 화면 안 상태로 두면 셋 다 깨진다.
 */
export function WhatIfPage() {
  const [params, setParams] = useSearchParams()
  const skills = withDesignFixture<readonly NextSkillFixture[]>([], () => NEXT_SKILLS)

  const requested = params.get('tech')
  const selected = skills.find((skill) => skill.techId === requested) ?? skills[0]
  const delta =
    selected === undefined ? 0 : selected.projectedFullMatch - selected.currentFullMatch

  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 다음 학습 기술
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="NEXT SKILL · WHAT-IF"
          title={selected?.headline ?? '이 기술을 목표 Level로 만들면 무엇이 달라질까요?'}
          description="공고 매칭과 같은 Snapshot에서, 특정 기술의 Personal Evidence가 목표 Level이 되었다고 가정한 결과입니다."
        />
        <DesignMockBadge />
      </div>

      {/*
        후보 순위 칩. v2가 hero 아래에 두는 전환 컨트롤이다. 후보가 없으면 그리지
        않는다 — 누를 것이 없는 탭 줄은 자리만 차지한다.
      */}
      {skills.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {skills.map((skill) => {
            const active = skill.techId === selected?.techId
            return (
              <button
                key={skill.techId}
                type="button"
                aria-pressed={active}
                onClick={() => setParams({ tech: skill.techId })}
                className={`flex items-center gap-2 rounded-[10px] px-3.5 py-2.5 text-[13px] font-bold transition-colors ${
                  active ? 'bg-tone-accent-bg text-brand-ink' : 'text-brand-faint hover:bg-[#F5F7FA]'
                }`}
              >
                <span className="text-[11px] font-extrabold text-brand-400">{skill.rank}</span>
                {skill.shortName}
                <span className="text-[12.5px] font-extrabold text-brand-600">
                  +{skill.projectedFullMatch - skill.currentFullMatch}
                </span>
              </button>
            )
          })}
        </div>
      )}

      {/* v2의 `571 / 757`. 왼쪽이 가정, 오른쪽이 그 결과로 새로 매칭되는 공고다. */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[571px_minmax(0,1fr)]">
        <DataRegion
          eyebrow={selected === undefined ? '#1 RECOMMENDED' : `${selected.rank} RECOMMENDED`}
          title="무엇을 가정하나"
          hint="현재 Level에서 목표 Level로 올라갔다고 가정합니다."
        >
          {selected === undefined ? (
            <>
              {/* 비교 축. 값이 없어도 두 칸을 세워 무엇이 대비되는지 남긴다 */}
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: '현재', caption: '지금 필수 기술을 모두 충족하는 공고' },
                  { label: '확보 후', caption: '목표 Level을 가정했을 때' },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5"
                  >
                    <p className="text-[12px] text-brand-faint">{item.label}</p>
                    <p className="mt-1.5 text-[15px] font-[750] text-brand-faint">계산 후 표시</p>
                    <p className="mt-1 text-[11.5px] leading-[1.5] text-brand-faint">
                      {item.caption}
                    </p>
                  </div>
                ))}
              </div>
              <div className="mt-3">
                <StateCard
                  kind="PREPARING"
                  title="What-if 결과 준비 중"
                  description="서버가 같은 Snapshot에서 다시 대조해 돌려주면 그대로 표시합니다. 화면에서 증가량을 만들어내지 않습니다."
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2.5">
                <h2 className="text-[22px] leading-[1.2] font-[750] tracking-[-0.03em] text-brand-ink">
                  {selected.techName}
                </h2>
                <LevelBadge level={selected.fromLevel} />
                <span aria-hidden className="text-[12px] text-brand-faint">
                  →
                </span>
                <span className="rounded-lg border border-brand-line bg-white px-2.5 py-1 text-[12px] font-[750] text-brand-ink-soft">
                  목표 {selected.targetLevel}
                </span>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3">
                <div className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
                  <p className="text-[12px] text-brand-faint">현재</p>
                  <p className="mt-1 text-[26px] leading-none font-[850] tracking-[-0.04em] text-brand-ink-soft">
                    {selected.currentFullMatch}
                  </p>
                  <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
                    지금 필수 기술을 모두 충족하는 공고
                  </p>
                </div>
                <div className="rounded-[14px] border border-brand-line-active bg-tone-accent-bg/40 px-4 py-3.5">
                  <p className="text-[12px] text-brand-faint">{selected.targetLevel} 확보 후</p>
                  <p className="mt-1 text-[26px] leading-none font-[850] tracking-[-0.04em] text-brand-600">
                    {selected.projectedFullMatch}
                  </p>
                  <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
                    목표 Level을 가정했을 때
                  </p>
                </div>
              </div>

              <div className="mt-4 flex gap-1">
                <div style={{ flex: Math.max(selected.currentFullMatch, 1) }}>
                  <MeterBar
                    value={selected.currentFullMatch}
                    total={selected.currentFullMatch}
                    tone="muted"
                    height={10}
                  />
                </div>
                <div style={{ flex: Math.max(delta, 1) }}>
                  <MeterBar value={delta} total={delta} height={10} />
                </div>
              </div>
              <p className="mt-2 text-[12px] text-brand-faint">
                현재 충족 {selected.currentFullMatch}건 · 새로 충족 {delta}건
              </p>

              <p className="mt-6 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
                추천 근거
              </p>
              <ul className="mt-2 grid gap-1.5">
                {selected.reasons.map((reason) => (
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

              <Link
                to={`/technologies/${selected.techId}`}
                className="mt-5 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3.5 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
              >
                {selected.ctaLabel}
              </Link>
            </>
          )}
        </DataRegion>

        <DataRegion
          eyebrow="NEWLY MATCHED"
          title={
            selected === undefined
              ? '새로 기술요건을 충족하는 공고'
              : `새로 기술요건을 충족하는 공고 ${delta}개`
          }
          hint="가정이 성립했을 때 비교 대상에 새로 들어오는 공고입니다."
          action={
            selected === undefined ? undefined : (
              <span className="shrink-0 text-[11.5px] text-brand-faint">
                {delta}건 중 {selected.newlyMatched.length}건 표시
              </span>
            )
          }
        >
          {selected === undefined ? (
            <StateCard
              kind="PREPARING"
              title="새로 매칭되는 공고 준비 중"
              description="어떤 공고가 새로 충족되는지, 그 공고가 어떤 기술을 요구하는지 함께 표시합니다."
            />
          ) : (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {selected.newlyMatched.map((job) => (
                <article
                  key={job.title}
                  className="rounded-[16px] border border-brand-line bg-white px-5 py-4"
                >
                  <p className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-600">
                    NEWLY MATCHED
                  </p>
                  <p className="mt-1.5 text-[14px] font-[750] tracking-[-0.02em] text-brand-ink">
                    {job.title}
                  </p>
                  <p className="mt-1 text-[12px] text-brand-faint">{job.meta}</p>
                  <div className="mt-3">
                    <RequirementChipList requirements={job.chips} />
                  </div>
                  <p className="mt-3 text-[12px] leading-[1.6] text-brand-muted">{job.why}</p>
                </article>
              ))}
            </div>
          )}
        </DataRegion>
      </div>

      {/* v2가 각주 위에 두는 복귀 이동. 가정을 접고 전체 공고로 돌아간다. */}
      <div className="mt-4 flex justify-end">
        <Link
          to="/jobs"
          className="rounded-xl border border-brand-line bg-white px-5 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
        >
          전체 공고로 돌아가기
        </Link>
      </div>

      <PageFootnote>
        {selected === undefined
          ? '공고 수 변화는 합격 가능성이 아니라, 해당 기술의 Personal Evidence를 목표 수준으로 올렸을 때 기술요건이 매칭되는 공고가 얼마나 늘어나는지를 뜻합니다.'
          : WHAT_IF_DISCLAIMER}
      </PageFootnote>
    </div>
  )
}
