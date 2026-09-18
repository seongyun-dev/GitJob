import { useState } from 'react'
import { Link } from 'react-router'
import { toSkillGapGroups, toSkillGapSummary } from '@/features/matching/api/adapter'
import {
  SkillGapRows,
  SKILL_GAP_TEMPLATE,
  VerdictBadge,
} from '@/features/matching/components/SkillGapRows'
import { useSkillGap, useTarget } from '@/features/matching/hooks/useMatching'
import {
  SKILL_GAP_DETAIL_TEXT,
  skillGapDetailRows,
} from '@/features/matching/model/skillGapDetail'
import type { SkillGapStatDetail } from '@/features/matching/model/skillGapDetail'
import type { SkillGapRowView, SkillGapSummaryView } from '@/features/matching/model/view'
import { hasComputedValue } from '@/shared/api/computeState'
import { ComputeStatePanel, PartialNotice } from '@/shared/ui/ComputeStatePanel'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { Modal } from '@/shared/ui/Modal'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import type { StatItem } from '@/shared/ui/StatStrip'

/**
 * Skill Gap · 확정 디자인 `Final v2`의 `17 Skill Gap` (S15P21E102-279).
 *
 * 이 화면이 답하는 질문은 **"무엇이 부족한가"** 하나다. "그럼 무엇을 먼저 배울까"는
 * 다음 화면(Next Skill / What-if)의 몫이라 여기서 순위를 매기지 않는다.
 *
 * **총점 · 취업 확률 · 역량 점수 · 부족도 %를 쓰지 않는다.** 충족 / 부족 /
 * 판단 근거 부족 구분만 쓴다. GitJob은 역량을 점수화하지 않는다.
 *
 * `채우면 +N`은 공고 수 증가분이고 C가 계산한다. 상위 후보에만 있는 값이라 대부분의
 * 행은 `—`다 — 0으로 채우면 "채워도 안 늘어난다"는 다른 사실이 된다.
 */
const GAP_COLUMNS = ['기술', '필수 요구', '우대 요구', '내 수준', '판정', '늘어나는 공고'] as const

/**
 * 지표 4연.
 *
 * 합을 화면에서 다시 만들지 않는다. 서버 값과 어긋났을 때 그 사실이 드러나야 한다.
 * `판단 근거 부족`이 `부족`과 다른 칸에 있는 것이 이 화면의 규칙이다.
 *
 * 네 칸 모두 **무언가를 센 값**이라 그 대상 목록을 열 수 있다(`내 기술` 화면과 같은
 * 규칙). 셀 대상이 없으면(0개) `onOpen`을 넘기지 않는다 -- 눌러도 빈 목록만 나오는
 * 버튼은 "볼 게 있다"는 거짓말이 된다.
 */
function toStats(
  summary: SkillGapSummaryView | null,
  rows: readonly SkillGapRowView[],
  onOpen: (detail: SkillGapStatDetail) => void,
): readonly StatItem[] {
  const opener = (detail: SkillGapStatDetail) =>
    skillGapDetailRows(rows, detail).length > 0 ? () => onOpen(detail) : undefined

  return [
    {
      label: '요구 기술',
      note: summary === null ? '대조 후 표시' : String(summary.requiredTechCount),
      caption: '필수 또는 우대로 1건 이상 언급',
      onOpen: opener('required'),
    },
    {
      label: '충족',
      note: summary === null ? '대조 후 표시' : String(summary.metCount),
      caption: '요구 Level 이상 보유',
      onOpen: opener('met'),
    },
    {
      label: '부족',
      note: summary === null ? '대조 후 표시' : String(summary.gapCount),
      caption: summary?.gapBreakdown ?? '미보유 · Level 부족',
      onOpen: opener('gap'),
    },
    {
      label: '판단 근거 부족',
      note: summary === null ? '대조 후 표시' : String(summary.undeterminedCount),
      caption: '평가하지 않음 · Gap으로 세지 않음',
      onOpen: opener('undetermined'),
    },
  ]
}

/**
 * 지표가 센 기술을 그대로 펼쳐 보이는 모달.
 *
 * 열리는 목록은 지표 caption과 **같은 기준**이라야 한다. 다른 기준의 목록을 보여주면
 * 숫자와 목록이 어긋난다. 행은 표와 같은 판정 배지·Level 배지를 써서 표에서 본 것과
 * 모달에서 본 것이 같은 사실로 읽히게 한다.
 */
function SkillGapDetailModal({
  detail,
  rows,
  onClose,
}: {
  detail: SkillGapStatDetail
  rows: readonly SkillGapRowView[]
  onClose: () => void
}) {
  const text = SKILL_GAP_DETAIL_TEXT[detail]
  const items = skillGapDetailRows(rows, detail)

  return (
    <Modal title={text.title} description={text.description} onClose={onClose}>
      <ul className="grid gap-2">
        {items.map((row) => (
          <li
            key={row.techName}
            className="flex items-center gap-3 rounded-[14px] border border-brand-line px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-[750] text-brand-ink">{row.techName}</p>
              {/* 수요 집계에 없는 축은 0건이 아니라 `—`다. 표의 규칙과 같다 */}
              <p className="mt-0.5 truncate text-[11.5px] tabular-nums text-brand-muted">
                필수 {row.requiredCount === null ? '—' : `${row.requiredCount}건`} · 우대{' '}
                {row.preferredCount === null ? '—' : `${row.preferredCount}건`}
              </p>
            </div>
            <span className="shrink-0">
              {row.personalLevel === null ? (
                <span className="text-[12.5px] text-brand-faint">없음</span>
              ) : (
                <LevelBadge level={row.personalLevel} />
              )}
            </span>
            <span className="shrink-0">
              <VerdictBadge row={row} />
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

const LEGEND = [
  { mark: '✓', label: '충족', detail: '공고에서 요구하는 수준 이상입니다.' },
  {
    mark: '△',
    label: '수준 부족',
    detail: '사용 근거는 있지만 공고의 요구 수준에는 미치지 못합니다.',
  },
  { mark: '✕', label: '미보유', detail: '선언·설정·구현 어느 것도 확인되지 않았습니다.' },
  {
    mark: '?',
    label: '판단 근거 부족',
    detail: '평가하지 않은 기술입니다. 부족과 다른 축이라 합산하지 않습니다.',
  },
] as const

export function SkillGapPage() {
  const target = useTarget()
  const skillGap = useSkillGap(target.data?.targetKey)

  const data = skillGap.data
  const groups = data === undefined ? [] : toSkillGapGroups(data.rows)
  const summary = data === undefined ? null : toSkillGapSummary(data)
  const ready = hasComputedValue(data)
  /** 지표 모달이 여는 대상. 묶음 순서를 그대로 이어 붙여 표와 같은 차례로 보이게 한다. */
  const rows = groups.flatMap((group) => group.rows)

  /** 어느 지표의 목록이 열려 있는지. 한 번에 하나만 연다. */
  const [openDetail, setOpenDetail] = useState<SkillGapStatDetail | null>(null)

  return (
    <div>
      <Link
        to="/jobs"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 공고 매칭
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero title="부족한 기술" />
        {summary !== null && (
          <div className="shrink-0 rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
            <p className="text-[12px] text-brand-faint">비교 집합</p>
            <p className="mt-1 text-[13.5px] font-[750] text-brand-ink-soft">
              {summary.basisText}
            </p>
          </div>
        )}
      </div>

      <div className="mt-7 grid gap-4">
        <PartialNotice state={data} />

        <ComputeStatePanel
          isLoading={target.isLoading || skillGap.isLoading}
          error={target.error ?? skillGap.error}
          state={data}
          loadingLabel="기술별 대조 결과를 불러오는 중입니다."
          onRetry={() => void skillGap.refetch()}
        />

        {ready && (
          <>
            <StatStrip items={toStats(summary, rows, setOpenDetail)} />

            <div className="gj-split">
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
                  <SkillGapRows groups={groups} />
                </div>
                <p className="border-t border-brand-line px-[22px] py-3 text-[11.5px] leading-[1.65] text-brand-faint">
                  늘어나는 공고 수는 그 기술을 공고의 요구 수준까지 익혔다고 가정한 결과입니다.
                </p>
              </div>

              <div className="grid gap-4">
                <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
                  <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
                    판정 기준
                  </p>
                  <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
                    네 가지로만 나눕니다
                  </h2>
                  <ul className="mt-4 grid gap-3">
                    {LEGEND.map((item) => (
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
                  <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
                    다음 단계
                  </p>
                  <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
                    그럼 무엇을 먼저 배울까요?
                  </h2>
                  <p className="mt-2 text-[12.5px] leading-[1.65] text-brand-muted">
                    {summary === null
                      ? '이 화면은 무엇이 부족한지까지만 보여줍니다.'
                      : `부족 ${summary.gapCount}개 중 공고 변화가 큰 순서는 다음 기술 추천에서 봅니다.`}
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
          </>
        )}
      </div>

      {openDetail !== null && (
        <SkillGapDetailModal
          detail={openDetail}
          rows={rows}
          onClose={() => setOpenDetail(null)}
        />
      )}
    </div>
  )
}
