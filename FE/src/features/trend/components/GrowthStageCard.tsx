import { GROWTH_STAGE_LABELS, GROWTH_STAGE_ORDER } from '@/mocks/fixtures/growthStage'
import type { GrowthStageAxisFixture, GrowthStageFixture } from '@/mocks/types'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 기술 성장 단계 카드 · S6 초안(트렌드 · 성장 단계).
 *
 * 초안이 답하려는 질문은 "이 기술을 지금 배울 타이밍인가"이고, 부제가 **"차트를
 * 보여주는 게 목적이 아니다"**라고 못 박는다. 그래서 이 카드는 추이 그래프를 그리지
 * 않고 단계 하나와 그 근거 축만 보여준다. 추이는 같은 화면 아래쪽
 * (`TrendDetailPage`의 시계열)이 담당한다.
 *
 * **판정과 근거를 분리해 보여주는 것이 이 컴포넌트의 규칙이다.** 세 축을 묶어 단계를
 * 정하는 것은 "출처를 합쳐 종합 점수를 만들지 않는다"는 규칙과 부딪히므로
 * (`docs/ai/c-public-trend.md` 30행), 단계를 점수처럼 보여주지 않고
 *   1. 단계는 네 칸 중 하나를 칠한 분류로,
 *   2. 축은 출처 이름과 단위를 붙여 따로,
 * 놓는다. 축마다 상태가 다를 수 있고 지원하지 않는 출처는 그 사실을 그대로 적는다.
 *
 * 단계 판정 규칙 자체는 아직 제품 결정이 없다. 그 결정 전까지 이 카드는 배치를 보기
 * 위한 자리이고, 값은 디자인 fixture에서 온다(`src/mocks/fixtures/growthStage.ts`).
 */

function AxisTile({ axis }: { axis: GrowthStageAxisFixture }) {
  return (
    <div className="rounded-[14px] border border-brand-line bg-[#F7F9FC] px-4 py-3.5">
      <p className="text-[10.5px] font-extrabold tracking-[0.1em] text-brand-600">
        {axis.sourceLabel}
      </p>
      <p className="mt-1.5 text-[13px] font-[750] text-brand-ink">{axis.label}</p>

      {/*
        값이 없는 축을 0으로 채우지 않는다. 미지원·준비 중은 오류가 아니고, 0은
        "확인했더니 없었다"는 다른 사실이 된다.
      */}
      {axis.valueText === null ? (
        <p className="mt-2 text-[12px] font-semibold text-brand-faint">{axis.status}</p>
      ) : (
        <div className="mt-2 flex flex-wrap items-baseline gap-2">
          <p className="text-[19px] leading-none font-[850] tracking-[-0.03em] text-brand-ink">
            {axis.valueText}
          </p>
          {axis.deltaText !== null && (
            <p
              className={`text-[12.5px] font-[750] ${
                axis.direction === 'UP' ? 'text-tone-success' : 'text-tone-caution'
              }`}
            >
              {axis.deltaText}
            </p>
          )}
        </div>
      )}

      <p className="mt-2 text-[11.5px] leading-[1.55] text-brand-faint">{axis.note}</p>
    </div>
  )
}

export function GrowthStageCard({ stage }: { stage: GrowthStageFixture | null }) {
  if (stage === null) {
    return (
      <StateCard
        kind="PREPARING"
        title="성장 단계를 아직 판정할 수 없어요"
        description="채용공고 언급 추이와 저장소 활동 추이가 모두 준비되면 단계를 표시합니다. 한 출처만으로 단계를 정하지 않습니다."
      />
    )
  }

  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-6 shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <h2 className="text-[18px] leading-[1.25] font-[750] tracking-[-0.03em] text-brand-ink">
        기술 성장 단계
      </h2>

      {/*
        stepper. 현재 단계만 채운다. 진행 막대처럼 왼쪽부터 누적해 칠하지 않는 이유는
        단계가 **달성도가 아니라 분류**이기 때문이다. 성숙기가 성장기보다 더 나아간
        상태도, 배우기에 더 좋은 상태도 아니다.

        칸 수는 `GROWTH_STAGE_ORDER`의 길이를 따라가야 하지만 Tailwind가 클래스명을
        정적으로 스캔하므로 문자열을 조립하지 않고 적어 둔다. 단계를 늘리거나 줄이면
        이 값도 함께 고친다.
      */}
      <ol className="mt-4 grid grid-cols-1 overflow-hidden rounded-[12px] border border-brand-line sm:grid-cols-3">
        {GROWTH_STAGE_ORDER.map((id) => {
          const active = id === stage.stage
          return (
            <li
              key={id}
              aria-current={active ? 'step' : undefined}
              className={`border-brand-line px-4 py-3 text-center text-[13px] max-sm:border-b max-sm:last:border-b-0 sm:border-r sm:last:border-r-0 ${
                active ? 'bg-brand-ink font-[750] text-white' : 'bg-white font-semibold text-brand-faint'
              }`}
            >
              {GROWTH_STAGE_LABELS[id]}
            </li>
          )
        })}
      </ol>

      <p className="mt-5 text-[19px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
        {stage.verdict}
      </p>
      <p className="mt-1.5 text-[14px] font-semibold text-brand-body">{stage.advice}</p>

      <p className="mt-6 text-[13px] font-[750] text-brand-ink">판정 근거 세 축</p>
      <div className="mt-2.5 grid grid-cols-1 gap-3 lg:grid-cols-3">
        {stage.axes.map((axis) => (
          <AxisTile key={axis.label} axis={axis} />
        ))}
      </div>

      <p className="mt-4 text-[11.5px] leading-[1.6] text-brand-faint">
        {stage.footnote} 세 축은 출처 · 단위 · 기간이 달라 합산하지 않습니다. 단계는 공개된
        규칙에 따른 분류이며 점수가 아닙니다.
      </p>
    </section>
  )
}
