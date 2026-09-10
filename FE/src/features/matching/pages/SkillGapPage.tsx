import { Link } from 'react-router'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
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
 * 표 열 폭도 v2 그대로다(`82 · 200 · 120 · 160 · 150 · 110`, gap 16).
 *   기술 / 필수 요구 / 우대 요구 / 내 EVIDENCE / 판정 / 채우면 +N
 *
 * **총점 · 취업 확률 · 역량 점수 · 부족도 %를 쓰지 않는다.** 충족 / 부족 /
 * 판단 근거 부족 세 구분만 쓴다. GitJob은 역량을 점수화하지 않는다.
 *
 * `채우면 +N`은 공고 수 증가분이고 C조가 계산한다. FE가 세지 않는다.
 */
const GAP_STATS = [
  { label: '요구 기술', note: '대조 후 표시', caption: '필수 또는 우대로 1건 이상 언급' },
  { label: '충족', note: '대조 후 표시', caption: '요구 Level 이상 보유' },
  { label: '부족', note: '대조 후 표시', caption: 'Evidence 없음 · Level 부족' },
  { label: '판단 근거 부족', note: '대조 후 표시', caption: '선언만 확인 · Gap으로 세지 않음' },
] as const

const GAP_COLUMNS = ['기술', '필수 요구', '우대 요구', '내 EVIDENCE', '판정', '채우면 +N'] as const
const GAP_TEMPLATE = '82px 200px 120px 160px 150px 110px'

export function SkillGapPage() {
  return (
    <div>
      <Link
        to="/jobs"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 공고 매칭
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="SKILL GAP"
          title="무엇이 충족됐고 무엇이 부족한가요?"
          description="비교 집합이 요구하는 기술을 내 Personal Evidence와 하나씩 대조합니다. 점수가 아니라 기술별 충족 · 부족 · 판단 근거 부족 구분입니다."
        />
      </div>

      <div className="mt-7">
        <StatStrip items={GAP_STATS} />
      </div>

      <div className="gj-split mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          {/*
            v2는 이 표를 판정별 그룹으로 나눈다(EVIDENCE 없음 / Level 부족 / 판단 근거 부족).
            그룹 헤더와 건수는 대조 결과가 있어야 만들 수 있어 지금은 컬럼만 세운다.
          */}
          <div
            className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
            style={{ gridTemplateColumns: GAP_TEMPLATE }}
          >
            {GAP_COLUMNS.map((label) => (
              <span key={label} className="truncate">
                {label}
              </span>
            ))}
          </div>
          <div className="p-4">
            <StateCard
              kind="PREPARING"
              title="대조 결과를 아직 불러올 수 없어요"
              description="요구 기술과 내 Evidence를 대조한 결과가 준비되면 이 표에 채워집니다. 부족한 기술과 판단 근거가 부족한 기술은 구분해 표시하며 합산하지 않습니다."
            />
          </div>
        </div>

        <div className="grid gap-4">
          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
              판정 구분
            </p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              세 가지로만 나눕니다
            </h2>
            <dl className="mt-4 grid gap-3.5">
              {[
                { t: '충족', d: '공고가 요구하는 Level 이상을 이미 보유한 기술' },
                { t: '부족', d: 'Evidence가 없거나 요구 Level에 이르지 못한 기술' },
                {
                  t: '판단 근거 부족',
                  d: '선언만 확인돼 판정할 수 없는 기술. 부족한 기술과 합산하지 않습니다',
                },
              ].map((item) => (
                <div key={item.t}>
                  <dt className="text-[13px] font-semibold text-brand-ink">{item.t}</dt>
                  <dd className="mt-0.5 text-[12.5px] leading-[1.6] text-brand-muted">{item.d}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">NEXT</p>
            <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
              그럼 무엇을 먼저 배울까요?
            </h2>
            <p className="mt-2 text-[12.5px] leading-[1.65] text-brand-muted">
              이 화면은 무엇이 부족한지까지만 보여줍니다. 어떤 기술을 먼저 채우면 비교 대상
              공고가 가장 많이 늘어나는지는 다음 화면에서 계산합니다.
            </p>
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
