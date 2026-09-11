import { Link } from 'react-router'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 목표 직무 선택 · 티켓 S15P21E102-212
 * (확정 디자인 `Final v2`의 `16 Target Role Selection`).
 *
 * v2 구조: hero(+우측 분석 요약) → 직무 카드 3열(실측 `437.3 x 3`, gap 16) → 각주.
 * 카드마다 비교할 공고 수 · 필수 전체 충족 수 · `자주 요구되는 기술 vs 내 EVIDENCE`
 * 대조 목록이 들어간다.
 *
 * **직무 목록을 하드코딩하지 않는다.** v2 아트보드가 이 영역에
 * `DESIGN MOCK ROLE TAXONOMY`라고 직접 적어 두었다. 즉 백엔드·데이터 엔지니어 같은
 * 이름은 레이아웃 검증용 예시이고 최종 taxonomy가 아니다. 제품 계약이 정해야 하며
 * 이를 돌려주는 조회 API도 develop에 없다.
 *
 * 카드 안의 공고 수와 충족 수도 마찬가지로 매칭 API가 계산한다. FE가 세지 않는다.
 */
export function TargetRolePage() {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TARGET ROLE"
          title="어떤 직무 공고와 비교할까요?"
          description="Evidence는 그대로 두고 비교할 공고 집합만 바꿉니다. 직무마다 요구 기술이 달라 같은 Evidence라도 충족 결과가 달라집니다."
        />
        <Link
          to="/evidence"
          className="shrink-0 rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
        >
          ← 내 Evidence
        </Link>
      </div>

      {/*
        직무 카드가 들어갈 3열. 값이 없어도 열 구조를 세워야 "직무마다 따로 비교한다"는
        것이 읽힌다. 카드는 조회 API가 직무 목록을 주면 이 자리에 채워진다.
      */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <StateCard
          kind="PREPARING"
          title="비교할 직무를 아직 불러올 수 없어요"
          description="직무 목록과 직무별 요구 기술을 돌려주는 조회 API가 준비되면 이 자리에 직무 카드가 놓입니다."
        />
        <StateCard
          kind="PREPARING"
          title="직무별 공고 수"
          description="직무마다 비교 대상 공고가 몇 건인지, 그중 필수 기술을 모두 충족하는 공고가 몇 건인지 함께 표시합니다."
        />
        <StateCard
          kind="PREPARING"
          title="요구 기술 대조"
          description="자주 요구되는 기술과 내 Evidence를 기술 단위로 나란히 놓아 어느 직무가 가까운지 비교합니다."
        />
      </div>

      {/*
        v2가 카드 아래 두는 직무 확정 바. 직무 이름과 공고 수는 조회 API가 주지만
        다음 화면으로 가는 이동은 그 값과 무관하다. 직무를 고르지 않아도 공고 매칭
        화면에서 바꿀 수 있으므로(아래 문구가 그렇게 약속한다) 이동을 막지 않는다.
      */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-[18px] border border-brand-line bg-white px-[22px] py-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            SELECTED ROLE
          </p>
          <p className="mt-1.5 text-[13.5px] leading-[1.6] text-brand-muted">
            언제든 공고 매칭 화면에서 직무를 바꿀 수 있습니다.
          </p>
        </div>
        <Link to="/jobs" className="shrink-0 rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]">
          공고 매칭으로
        </Link>
      </div>

      <PageFootnote>
        직무는 비교 기준일 뿐 사용자를 분류하지 않습니다. 공고 수는 현재 수집된 공고 집합의
        크기이며 채용시장 전체 규모가 아닙니다. 직무 목록은 제품 계약이 확정한 값을 사용하며
        화면에서 만들지 않습니다.
      </PageFootnote>
    </div>
  )
}
