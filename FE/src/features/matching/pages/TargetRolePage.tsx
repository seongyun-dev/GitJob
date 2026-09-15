import { useState } from 'react'
import { Link } from 'react-router'
import type { JobRole } from '@/features/matching/api/types'
import { TargetRoleCard } from '@/features/matching/components/TargetRoleCard'
import { useJobRoles } from '@/features/matching/hooks/useMatching'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { TARGET_ROLES, TARGET_ROLE_EVIDENCE_TEXT } from '@/mocks/fixtures/targetRole'
import type { TargetRoleFixture } from '@/mocks/types'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 목표 직무 선택 · 티켓 S15P21E102-212
 * (확정 디자인 `Final v2`의 `16 Target Role Selection`).
 *
 * v2 구조: hero(+우측 분석 요약) → 직무 카드 3열(실측 `437.3 x 3`, gap 16) → 각주.
 *
 * **직무 목록은 확정 taxonomy가 아니다.** v2 아트보드가 이 영역에
 * `DESIGN MOCK ROLE TAXONOMY`라고 직접 적어 두었다. 그래서 값이 디자인 fixture에
 * 있고 화면에도 `DESIGN MOCK` 배지를 남긴다. 최종 목록은 제품 계약이 정하며 이를
 * 돌려주는 조회 API도 develop에 없다.
 *
 * 카드 안의 공고 수와 충족 수도 매칭 API가 계산한다. FE가 세지 않는다.
 *
 * 선택 상태는 화면이 갖는다(`useState`). 서버에 저장하는 값이 아니라 다음 화면으로
 * 넘길 비교 기준이고, 저장 API도 없다. 실제로는 라우트 쿼리나 전역 상태로 옮겨야
 * 하지만 그 결정은 매칭 API 계약과 함께 정해진다.
 */
/**
 * 응답을 카드가 받는 모양으로 옮긴다 · 티켓 S15P21E102-281.
 *
 * `kicker`(`ROLE 01`)만 여기서 만든다. 순번은 판정이 아니라 **목록에서 몇 번째인가**일
 * 뿐이고 배열 순서에서 곧바로 나오는 표시 환산이다. 서버가 보내면 배열 순서와 어긋날
 * 수 있는 값이 하나 늘어난다 — 그래서 계약(`api/types.ts`)에 두지 않았다.
 *
 * 나머지 필드는 손대지 않는다. 공고 수·충족 수·요구 기술 대조는 전부 서버가 센 값이다.
 */
function toRoleView(role: JobRole, index: number): TargetRoleFixture {
  return { ...role, kicker: `ROLE ${String(index + 1).padStart(2, '0')}` }
}

export function TargetRolePage() {
  const query = useJobRoles()
  const roles = withDesignFixture<readonly TargetRoleFixture[]>(
    query.data?.roles.map(toRoleView) ?? [],
    () => TARGET_ROLES,
  )
  /*
   * 선택을 초기값이 아니라 파생값으로 둔다 · 티켓 S15P21E102-281.
   *
   * 전에는 `useState(roles[0]?.id)`였다. fixture는 첫 렌더에 이미 값이 있어 동작했지만,
   * 조회 응답은 나중에 도착하므로 초기값이 `undefined`로 굳어 카드가 하나도 선택되지
   * 않은 채 남는다. 고른 적이 없으면 첫 직무를 보여주고, 고르는 순간부터 그 선택을
   * 따른다.
   */
  const [pickedId, setPickedId] = useState<string | undefined>(undefined)
  const selected = roles.find((role) => role.id === pickedId) ?? roles[0]

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="TARGET ROLE"
          title="어떤 직무 공고와 비교할까요?"
          description="Evidence는 그대로 두고 비교할 공고 집합만 바꿉니다. 직무마다 요구 기술이 달라 같은 Evidence라도 충족 결과가 달라집니다."
        />
        <div className="flex shrink-0 flex-wrap items-center gap-2.5">
          {roles.length > 0 && (
            <div className="rounded-[14px] border border-brand-line bg-white px-5 py-3.5">
              <p className="text-[12px] text-brand-faint">분석 결과</p>
              <p className="mt-1 text-[13px] font-[750] text-brand-ink-soft">
                {TARGET_ROLE_EVIDENCE_TEXT}
              </p>
            </div>
          )}
          <DesignMockBadge label="DESIGN MOCK ROLE TAXONOMY" />
          <Link
            to="/evidence"
            className="rounded-xl border border-brand-line bg-white px-5 py-3 text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
          >
            ← 내 Evidence
          </Link>
        </div>
      </div>

      {/*
        직무 카드 3열. 값이 없어도 열 구조를 세워야 "직무마다 따로 비교한다"는 것이
        읽히므로, 비어 있을 때도 같은 그리드 안에 상태 카드를 둔다.
      */}
      <div className="mt-7 grid grid-cols-1 gap-4 lg:grid-cols-3">
        {roles.length === 0 ? (
          <>
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
          </>
        ) : (
          roles.map((role) => (
            <TargetRoleCard
              key={role.id}
              role={role}
              selected={role.id === selected?.id}
              onSelect={() => setPickedId(role.id)}
            />
          ))
        )}
      </div>

      {/*
        v2가 카드 아래 두는 직무 확정 바. 직무를 고르지 않아도 공고 매칭 화면에서
        바꿀 수 있으므로(아래 문구가 그렇게 약속한다) 이동을 막지 않는다.
      */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-[18px] border border-brand-line bg-white px-[22px] py-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            SELECTED ROLE
          </p>
          {selected === undefined ? (
            <p className="mt-1.5 text-[13.5px] leading-[1.6] text-brand-muted">
              언제든 공고 매칭 화면에서 직무를 바꿀 수 있습니다.
            </p>
          ) : (
            <>
              <p className="mt-1.5 text-[15px] font-[750] tracking-[-0.02em] text-brand-ink">
                {selected.name} · {selected.jobCount}건 공고와 비교
              </p>
              <p className="mt-1 text-[12.5px] text-brand-muted">
                언제든 공고 매칭 화면에서 직무를 바꿀 수 있습니다.
              </p>
            </>
          )}
        </div>
        <Link
          to="/jobs"
          className="shrink-0 rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-5 py-3 text-center text-[13.5px] font-[750] text-white shadow-[0_12px_26px_rgba(47,94,235,0.24)]"
        >
          {selected === undefined ? '공고 매칭으로' : '이 직무로 공고 비교'}
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
