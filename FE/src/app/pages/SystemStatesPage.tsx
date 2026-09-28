import { CodePath, EvidenceKind } from '@/shared/ui/CodePath'
import { PageFootnote } from '@/shared/ui/DataRegion'
import { LevelBadge, LevelLadder, LevelLegend } from '@/shared/ui/LevelBadge'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'
import type { StateKind } from '@/shared/ui/StateCard'
import { EVIDENCE_LEVELS } from '@/shared/types/domain'

/**
 * 상태 · 표기 레퍼런스 · 티켓 S15P21E102-204
 * (확정 디자인 `Final v2`의 `15 System States`).
 *
 * 팀이 상태 어휘와 표기를 한 화면에서 대조하기 위한 **레퍼런스 보드**다. 사용자 흐름에
 * 속하지 않으므로 헤더 네비게이션에 넣지 않는다. v2도 아트보드로만 두었다.
 *
 * v2가 정한 원칙을 그대로 옮긴다.
 *   "데이터가 없는 상태와 실제 오류는 색과 문구로 구분합니다.
 *    중립(회색) = 데이터 범위의 문제, Warning = 대기 · 부분, Danger = 실패."
 *
 * 문구는 v2의 것을 쓴다. 이건 사용자 데이터가 아니라 **상태 어휘의 정의**라 화면에
 * 그대로 놓아야 팀이 같은 말을 쓴다.
 *
 * Level 배지 · 사다리 · 코드 경로 표기도 여기서 함께 보여준다. 조회 API가 붙기 전까지
 * 표 행이 없어 실제 화면에서 볼 기회가 없는데, 표기 규칙은 지금 합의해야 한다.
 */
const STATES: ReadonlyArray<{ kind: StateKind; title: string; description: string }> = [
  {
    kind: 'LOADING',
    title: '불러오는 중',
    description: '스켈레톤으로 구조를 먼저 보여줍니다. 스피너만 단독으로 쓰지 않습니다.',
  },
  {
    kind: 'EMPTY',
    title: '조건에 맞는 결과가 없어요',
    description: '조건을 넓히면 다시 비교할 수 있습니다. 오류가 아닙니다.',
  },
  {
    kind: 'ERROR',
    title: '불러오지 못했어요',
    description: '일시적인 문제입니다. 다시 시도해도 반복되면 알려주세요.',
  },
  {
    kind: 'PARTIAL',
    title: '일부만 분석됐어요',
    description: '완료된 범위까지는 그대로 유지되고, 나머지는 재분석으로 채울 수 있습니다.',
  },
  {
    kind: 'RATE_LIMITED',
    title: 'GitHub 호출 한도 대기 중',
    description: '한도가 풀리면 자동으로 다시 시작됩니다. 부분 결과는 유지됩니다.',
  },
  {
    kind: 'PREPARING',
    title: '데이터를 준비하고 있어요',
    description: '이 지표는 곧 제공됩니다. 다른 영역은 먼저 확인할 수 있어요.',
  },
  {
    kind: 'INSUFFICIENT_DATA',
    title: '판정할 Evidence가 부족해요',
    description: '선언만 확인되어 Level을 판정하지 않았습니다. 부족한 기술과 구분해 셉니다.',
  },
  {
    kind: 'NO_DATA',
    title: '이 출처에는 데이터가 없어요',
    description: '기간 내 수집된 항목이 없습니다. 오류는 아닙니다.',
  },
  {
    kind: 'NOT_SUPPORTED',
    title: '이 출처는 지원하지 않아요',
    description: '출처가 그 지표를 제공하지 않습니다. 데이터가 없는 것과 다릅니다.',
  },
]

export function SystemStatesPage() {
  return (
    <div>
      <PageHero
        eyebrow="SYSTEM STATES"
        title="상태 · 표기 레퍼런스"
        description="데이터가 없는 상태와 실제 오류는 색과 문구로 구분합니다. 중립(회색)은 데이터 범위의 문제, 주의는 대기 · 부분, 위험은 실패입니다."
      />

      {/* v2의 `259.2 x 5`. 상태 아홉 개를 한 눈에 대조한다. */}
      <div className="gj-cards mt-7 lg:grid-cols-5">
        {STATES.map((state) => (
          <StateCard
            key={state.kind}
            kind={state.kind}
            title={state.title}
            description={state.description}
          />
        ))}
      </div>

      <section className="mt-6 rounded-[18px] border border-brand-line bg-white p-6 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
        <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">NOTATION</p>
        <h2 className="mt-1.5 text-[18px] font-[750] tracking-[-0.03em] text-brand-ink">
          Level과 근거 표기
        </h2>

        <div className="mt-5 grid gap-5">
          <div>
            <p className="text-[12.5px] font-semibold text-brand-muted">Level 범례</p>
            <div className="mt-2">
              <LevelLegend />
            </div>
          </div>

          <div>
            <p className="text-[12.5px] font-semibold text-brand-muted">
              배지 · 사다리 (PERSONAL 열 / REPOSITORY 열)
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-3">
              {EVIDENCE_LEVELS.map((level) => (
                <span key={level} className="inline-flex items-center gap-2">
                  <LevelBadge level={level} />
                  <LevelLadder level={level} />
                  <LevelBadge level={level} variant="repository" />
                </span>
              ))}
            </div>
          </div>

          <div>
            <p className="text-[12.5px] font-semibold text-brand-muted">근거 유형과 코드 위치</p>
            <div className="mt-2 flex flex-wrap items-center gap-2.5">
              <EvidenceKind>DEP</EvidenceKind>
              <EvidenceKind>CFG</EvidenceKind>
              <EvidenceKind>IMPL</EvidenceKind>
              <CodePath>build.gradle</CodePath>
              <CodePath>KafkaConfig.java:24</CodePath>
            </div>
            <p className="mt-2 text-[12px] leading-[1.6] text-brand-faint">
              유형 값은 판정 결과가 주는 값이라 화면이 목록을 닫지 않습니다. 표기 형태만 고정합니다.
            </p>
          </div>
        </div>
      </section>

      <PageFootnote>
        이 화면은 팀 내부 표기 레퍼런스입니다. 사용자 흐름에 속하지 않아 네비게이션에 넣지
        않습니다. 상태 어휘를 늘리기 전에 확정 디자인을 먼저 확인하세요.
      </PageFootnote>
    </div>
  )
}
