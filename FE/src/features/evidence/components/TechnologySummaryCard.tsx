import type { TechnologySummary } from '@/features/evidence/api/technologiesApi'
import {
  profileErrorMessage,
  useTechnologySummary,
} from '@/features/evidence/hooks/useTechnologyProfile'
import {
  evidenceSummaryText,
  missingEvidenceGuide,
} from '@/features/evidence/model/summaryPresentation'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 판정 위에 얹는 한 문단 · 티켓 S15P21E102-137.
 *
 * <h2>왜 출처를 밝히는가</h2>
 *
 * 이 제품은 "점수가 아니라 근거"를 말한다. 규칙으로 판정한 Level 옆에 출처 표시가
 * 없는 생성 문장을 놓으면 둘이 같은 무게로 읽힌다. 그래서 eyebrow 와 각주가
 * **AI 가 쓴 문장**이라는 것을 먼저 말한다. 판정은 이 문단과 무관하게 이미 끝나
 * 있다.
 *
 * <h2>없어도 화면이 깨지지 않는다</h2>
 *
 * 생성은 노트북 GPU 위에서 돌아 꺼져 있는 일이 정상적으로 자주 있다. 그래서
 * 요약이 없는 것을 오류로 그리지 않는다 -- 붉은 카드를 띄우면 멀쩡한 판정 결과가
 * 고장 난 것처럼 읽힌다. 근거 표와 permalink 는 이 호출과 상관없이 이미 있다.
 *
 * 문장 내용은 손대지 않고, API 응답에 들어온 줄바꿈과 연속 공백만 한 문단으로
 * 정리한다. 길이(40자·200자)와 금지 표현(비율·등급 단어·`L0`~`L3`)은 AI 쪽
 * 검증이 이미 보장하므로 화면이 다시 자르면 문장만 망가진다.
 */
/**
 * `card` 는 화면에 홀로 놓이는 자리(상세), `inline` 은 이미 카드 안인 자리(목록의
 * 펼친 행)다. 카드 안에 카드를 겹쳐 그리면 어디까지가 한 덩어리인지 흐려진다.
 */
const SURFACE: Readonly<Record<'card' | 'inline', string>> = {
  card: 'rounded-[18px] border border-brand-line bg-white p-5 shadow-[0_10px_28px_rgba(25,47,81,0.07)] 3xl:p-6',
  inline: 'rounded-[14px] border border-brand-line bg-brand-box/20 p-4',
}

export function TechnologySummaryCard({
  techId,
  enabled = true,
  variant = 'card',
}: {
  techId: string | undefined
  /** 목록 화면이 "지금 이 기술을 보고 있다"고 말할 때만 켜기 위한 자리 */
  enabled?: boolean
  variant?: 'card' | 'inline'
}) {
  const query = useTechnologySummary(techId, enabled)

  return (
    <section className={SURFACE[variant]}>
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">근거 요약</p>
      <p className="mt-1.5 text-[12.5px] leading-[1.6] text-brand-muted">
        확인된 사용 근거를 쉽게 풀어쓴 설명입니다.
      </p>

      <div className="mt-4">
        <SummaryBody
          loading={query.isPending}
          fetching={query.isFetching}
          error={query.isError ? profileErrorMessage(query.error) : null}
          data={query.data}
          onRetry={() => void query.refetch()}
        />
      </div>
    </section>
  )
}

function SummaryBody({
  loading,
  fetching,
  error,
  data,
  onRetry,
}: {
  loading: boolean
  fetching: boolean
  error: string | null
  data: TechnologySummary | undefined
  onRetry: () => void
}) {
  /*
   * 첫 조회와 `PENDING` 을 같은 얼굴로 둔다. 둘 다 "곧 온다"이고, 사용자가 할 일도
   * 기다리는 것으로 같다. 생성에 4초쯤 걸리므로 스피너 대신 들어올 자리의 모양을
   * 먼저 그린다.
   */
  if (loading || data?.status === 'PENDING') {
    return (
      <div role="status" aria-live="polite">
        <SummarySkeleton />
        <p className="mt-3 text-[12.5px] text-brand-faint">
          요약을 만들고 있어요. 먼저 만들어지는 순서가 있어 조금 걸릴 수 있습니다.
        </p>
        {/*
          자동 재시도에는 상한이 있다(훅의 `MAX_PENDING_POLLS`). 상한에 닿은 뒤에도
          사용자가 다시 부를 길이 있어야 해서 버튼을 남긴다. 조회 중에는 누를 것이
          없으므로 그때만 감춘다.
        */}
        {!fetching && (
          <RetryButton onClick={onRetry} label="다시 시도" />
        )}
      </div>
    )
  }

  /*
   * 조회 실패와 `NONE` 을 같은 톤으로 그린다. 둘 다 "지금은 문장이 없다"이고,
   * 이 자리는 판정을 보조하는 문단이라 화면 전체를 실패로 물들일 이유가 없다.
   * 다만 사유는 구분해 적는다 -- 서비스가 꺼진 것과 조회가 실패한 것은 다르다.
   */
  if (error !== null) {
    return (
      <StateCard
        kind="NO_DATA"
        title="요약을 불러오지 못했어요"
        description={error}
        action={<RetryButton onClick={onRetry} label="다시 시도" />}
      />
    )
  }

  if (data === undefined || data.status !== 'READY' || data.summary === null) {
    return (
      <StateCard
        kind="NO_DATA"
        title="지금은 요약이 없어요"
        description="요약 생성이 꺼져 있거나 문장을 만들 근거가 부족했습니다. 아래 판정 근거는 이와 무관하게 그대로입니다."
        action={<RetryButton onClick={onRetry} label="다시 시도" />}
      />
    )
  }

  return (
    <div>
      {/* headline 은 40자 이내이고 Level 문자열을 담지 않는다 -- Level 은 위에 따로 있다. */}
      {data.headline !== null && (
        <h3 className="max-w-[64ch] text-[16px] leading-[1.4] font-[750] tracking-[-0.02em] text-brand-ink">
          {evidenceSummaryText(data.headline)}
        </h3>
      )}
      <p className="mt-2 max-w-[64ch] text-[13.5px] leading-[1.75] text-brand-ink-soft">
        {evidenceSummaryText(data.summary)}
      </p>

      {/*
        `gap` 은 다음 수준까지 무엇이 비었는지다. 도달 가능한 최고 수준이면 null 이라
        **줄 자체를 그리지 않는다.** 빈 자리를 남기면 "부족한 것이 없다"로 읽힌다.
      */}
      {missingEvidenceGuide(data.gap) !== null && (
        <div className="mt-4 rounded-[14px] border border-brand-line bg-tone-accent-bg/40 px-4 py-3">
          <p className="text-[11px] font-extrabold tracking-[0.12em] text-brand-600">
            아직 확인되지 않은 것
          </p>
          <p className="mt-1.5 max-w-[64ch] text-[12.5px] leading-[1.7] text-brand-ink-soft">
            {missingEvidenceGuide(data.gap)}
          </p>
        </div>
      )}

      {/*
        `confidence` 는 자신감이 아니라 **입력이 얼마나 구체적인가**다. 의존성 선언만
        확인된 기술은 문장이 맞아도 LOW 다. HIGH 를 배지로 띄우면 "이 판정이 확실하다"로
        오독되므로, 문장을 그대로 믿기 어려운 LOW 일 때만 그 사실을 적는다.
      */}
      {data.confidence === 'LOW' && (
        <p className="mt-3 text-[12px] leading-[1.6] text-brand-faint">
          확인된 근거가 적어 일반적인 설명에 가깝습니다. 아래 판정 근거를 함께 보세요.
        </p>
      )}
    </div>
  )
}

/**
 * 들어올 문단의 모양.
 *
 * 스피너를 쓰지 않는 것은 확정 디자인의 규정이다 -- 구조를 먼저 보여주고 값이
 * 채워지게 한다. 줄 길이를 다르게 둔 것은 실제 문단이 그렇게 끝나기 때문이다.
 */
function SummarySkeleton() {
  return (
    <div aria-hidden className="grid gap-2.5">
      <span className="h-[18px] w-[58%] rounded-md bg-[#E4E9F2]" />
      <span className="h-[13px] w-full rounded bg-[#EDF1F7]" />
      <span className="h-[13px] w-full rounded bg-[#EDF1F7]" />
      <span className="h-[13px] w-[72%] rounded bg-[#EDF1F7]" />
    </div>
  )
}

function RetryButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-3 rounded-lg border border-brand-line px-3 py-1.5 text-[12.5px] font-bold text-brand-muted hover:border-brand-line-active"
    >
      {label}
    </button>
  )
}
