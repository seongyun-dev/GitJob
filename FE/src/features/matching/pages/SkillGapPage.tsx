import { Link } from 'react-router'
import { SkillGapRows, SKILL_GAP_TEMPLATE } from '@/features/matching/components/SkillGapRows'
import { useRecommendations, useSkillGap } from '@/features/matching/hooks/useMatching'
import { toNextSkillViews } from '@/features/matching/lib/nextSkillView'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { NEXT_SKILLS } from '@/mocks/fixtures/nextSkill'
import {
  SKILL_GAP_FOOTNOTE,
  SKILL_GAP_GROUPS,
  SKILL_GAP_LEGEND,
  SKILL_GAP_SUMMARY,
} from '@/mocks/fixtures/skillGap'
import type {
  NextSkillFixture,
  SkillGapGroupFixture,
  SkillGapSummaryFixture,
} from '@/mocks/types'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import type { StatItem } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Skill Gap · 티켓 S15P21E102-204 (확정 디자인 `Final v2`의 `17 Skill Gap`).
 *
 * 이 화면이 답하는 질문은 **"무엇이 부족한가"** 하나다. "그럼 무엇을 먼저 배울까"는
 * 다음 화면(Next Skill / What-if)의 몫이라 여기서 순위를 매기지 않는다.
 *
 * v2 구조: hero(+비교 집합 표시) → 지표 4연(실측 `335.5 x 4`) → `956/372` split
 * (기술별 대조 표 | 요약) → 각주.
 *
 * 표 열 폭도 v2 그대로이며 `SkillGapRows`가 그 값을 갖는다(헤더와 본문이 어긋나지
 * 않도록 한 곳에서 정한다).
 *   기술 / 필수 요구 / 우대 요구 / 내 EVIDENCE / 판정 / 채우면 +N
 *
 * **총점 · 취업 확률 · 역량 점수 · 부족도 %를 쓰지 않는다.** 충족 / 부족 /
 * 판단 근거 부족 구분만 쓴다. GitJob은 역량을 점수화하지 않는다.
 *
 * `채우면 +N`은 공고 수 증가분이고 C조가 계산한다. FE가 세지 않는다. 조회 API가
 * 없어 값은 디자인 fixture에서 온다(`VITE_DESIGN_FIXTURES=on`).
 */
const GAP_COLUMNS = ['기술', '필수 요구', '우대 요구', '내 EVIDENCE', '판정', '채우면 +N'] as const

/**
 * 지표 4연.
 *
 * `요구 기술 = 충족 + 부족 + 판단 근거 부족`이 성립해야 화면이 스스로 모순되지
 * 않는다. fixture가 그 관계를 지키고 있고, 여기서 다시 더하지 않는 이유는 합을
 * 화면이 만들면 서버 값과 어긋났을 때 그 사실이 감춰지기 때문이다.
 */
function toStats(summary: SkillGapSummaryFixture | null): readonly StatItem[] {
  return [
    {
      label: '요구 기술',
      note: summary === null ? '대조 후 표시' : String(summary.requiredTechCount),
      caption: '필수 또는 우대로 1건 이상 언급',
    },
    {
      label: '충족',
      note: summary === null ? '대조 후 표시' : String(summary.metCount),
      caption: '요구 Level 이상 보유',
    },
    {
      label: '부족',
      note: summary === null ? '대조 후 표시' : String(summary.gapCount),
      caption: summary?.gapBreakdown ?? 'Evidence 없음 · Level 부족',
    },
    {
      label: '판단 근거 부족',
      note: summary === null ? '대조 후 표시' : String(summary.undeterminedCount),
      caption: '선언만 확인 · Gap으로 세지 않음',
    },
  ]
}

export function SkillGapPage() {
  const query = useSkillGap()
  const groups = withDesignFixture<readonly SkillGapGroupFixture[]>(
    query.data?.groups ?? [],
    () => SKILL_GAP_GROUPS,
  )
  const summary = withDesignFixture<SkillGapSummaryFixture | null>(
    query.data?.summary ?? null,
    () => SKILL_GAP_SUMMARY,
  )

  /*
   * 하단 "무엇을 먼저 배울까요" 목록 · 티켓 S15P21E102-281.
   *
   * 추천 화면과 **같은 훅**을 쓴다. react-query가 키로 요청을 합치므로 두 화면이
   * 같은 응답을 본다 — 따로 부르면 그 사이 서버 값이 바뀌었을 때 두 화면의 숫자가
   * 어긋난다. 전에 `NEXT_SKILLS`를 직접 import하던 자리이고, 그 직접 import는
   * `src/mocks/README.md`가 금지한 형태였다(반드시 `withDesignFixture`를 거친다).
   */
  const recommendations = useRecommendations()
  const nextSkills = withDesignFixture<readonly NextSkillFixture[]>(
    toNextSkillViews(recommendations.data?.skills),
    () => NEXT_SKILLS,
  )

  return (
    <div>
      <Link
        to="/jobs"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 공고 매칭
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="SKILL GAP · 상세"
          title={
            summary === null
              ? '무엇이 충족됐고 무엇이 부족한가요?'
              : `무엇이 부족한가 — ${summary.basisText} 기준`
          }
          description="비교 집합이 요구하는 기술을 내 Personal Evidence와 하나씩 대조합니다. 점수가 아니라 기술별 충족 · 부족 · 판단 근거 부족 구분입니다."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          <DesignMockBadge />
          {summary !== null && (
            <div className="rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
              <p className="text-[12px] text-brand-faint">비교 집합</p>
              <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
                {summary.basisText}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-7">
        <StatStrip items={toStats(summary)} />
      </div>

      <div className="gj-split mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <div
            className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
            style={{ gridTemplateColumns: SKILL_GAP_TEMPLATE }}
          >
            {GAP_COLUMNS.map((label) => (
              <span key={label} className="truncate">
                {label}
              </span>
            ))}
          </div>
          <div className="p-4">
            {groups.length === 0 ? (
              <StateCard
                kind="PREPARING"
                title="대조 결과를 아직 불러올 수 없어요"
                description="요구 기술과 내 Evidence를 대조한 결과가 준비되면 이 표에 채워집니다. 부족한 기술과 판단 근거가 부족한 기술은 구분해 표시하며 합산하지 않습니다."
              />
            ) : (
              <SkillGapRows groups={groups} />
            )}
          </div>
          {groups.length > 0 && (
            <p className="border-t border-brand-line px-[22px] py-3 text-[11.5px] leading-[1.65] text-brand-faint">
              {SKILL_GAP_FOOTNOTE}
            </p>
          )}
        </div>

        <div className="grid gap-4">
          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">판정 기준</p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              네 가지로만 나눕니다
            </h2>
            {/*
              범례를 네 줄로 둔다. 표의 배지가 네 종류이고(✓ △ ✕ ?) 그중 `?`가 나머지
              셋과 다른 축이라는 것이 이 화면의 규칙이므로, 셋만 적으면 표에 실제로
              찍히는 표시를 설명하지 못한다.
            */}
            <ul className="mt-4 grid gap-3">
              {SKILL_GAP_LEGEND.map((item) => (
                <li key={item.label} className="flex items-start gap-2.5">
                  <span
                    aria-hidden
                    className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md bg-tone-neutral-bg text-[11px] font-black text-tone-neutral"
                  >
                    {item.mark}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-brand-ink">{item.label}</p>
                    <p className="mt-0.5 text-[12px] leading-[1.6] text-brand-muted">
                      {item.detail}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">NEXT</p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              그럼 무엇을 먼저 배울까요?
            </h2>
            <p className="mt-2 text-[12.5px] leading-[1.65] text-brand-muted">
              {summary === null
                ? '이 화면은 무엇이 부족한지까지만 보여줍니다. 어떤 기술을 먼저 채우면 비교 대상 공고가 가장 많이 늘어나는지는 다음 화면에서 계산합니다.'
                : `부족 ${summary.gapCount}개 중 공고 변화가 큰 순서는 다음 기술 추천에서 봅니다.`}
            </p>

            {/*
              순위를 이 화면에서 매기지 않는다는 규칙은 지키되, 다음 화면이 어떤
              기준으로 정렬하는지는 미리 밝힌다. 값을 추천 화면과 같은 fixture에서
              가져오는 이유는 두 화면의 숫자가 어긋나지 않게 하려는 것이다.
            */}
            {groups.length > 0 && nextSkills.length > 0 && (
              <ol className="mt-4 grid gap-2">
                {nextSkills.map((skill, index) => (
                  <li
                    key={skill.techId}
                    className="flex items-center gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                  >
                    <span className="text-[11px] font-extrabold tabular-nums text-brand-faint">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-[750] text-brand-ink">
                        {skill.techName}
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-brand-faint">
                        {skill.fromLevel === 'L0' ? '없음' : skill.fromLevel} → {skill.targetLevel}
                      </p>
                    </div>
                    <span className="shrink-0 text-[13px] font-[850] text-brand-600">
                      +{skill.projectedFullMatch - skill.currentFullMatch}
                    </span>
                  </li>
                ))}
              </ol>
            )}

            <Link
              to="/recommendations"
              className="mt-4 block rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-4 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
            >
              다음 학습 기술 보기
            </Link>
          </section>
        </div>
      </div>

      <PageFootnote>
        충족 · 부족은 기술 요건의 대조 결과이며 합격 가능성이나 역량 점수가 아닙니다. 판단 근거가
        부족한 기술은 부족한 기술과 분리해 표시하며 둘을 합산하지 않습니다.
      </PageFootnote>
    </div>
  )
}
