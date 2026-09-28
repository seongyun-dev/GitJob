import { Fragment } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { AnalysisStartLink } from '@/features/landing/components/AnalysisStartLink'
import { FlowConnector, FlowNode } from '@/features/landing/components/FlowRail'
import {
  ArrowUpIcon,
  BriefcaseIcon,
  CompassIcon,
  GithubIcon,
  LayersIcon,
  RepoIcon,
  SearchIcon,
} from '@/features/landing/landingIcons'
import {
  EVIDENCE_BARS,
  MARKET_CARDS,
  NEXT_STEPS,
  REPO_ROWS,
} from '@/features/landing/serviceIntroData'

/**
 * 랜딩 첫 장 아래의 소개 장들 · Landing Redesign.
 *
 * 확정 디자인 `GitJob Landing Redesign`의 장면 2~5를 옮겼다. 첫 장(Hero + 미리보기
 * 패널)은 그대로 두고 그 아래만 이 구성으로 바꾼 것이다.
 *
 * 한 장에 메시지 하나다. 01은 무엇을 읽는지, 02는 그것이 무엇과 만나는지, 03은 다음에
 * 무엇을 하는지. 마지막 장이 시작 지점을 준다.
 *
 * 이전 버전은 한 장에 카드 여러 개와 설명 문단을 함께 담았다. 스냅으로 한 장씩
 * 넘기는 화면에서는 한 번에 읽히는 양이 그만큼이어야 하는데, 문단까지 있으면 장이
 * 넘어가기 전에 다 읽지 못한다.
 *
 * 문구는 `serviceIntroData`가 갖는다.
 */

/**
 * 장 하나의 골격.
 *
 * `min-h-dvh`인 것은 스냅 경계와 화면 경계가 같아야 하기 때문이다. 고정 높이를 주면
 * 창 높이에 따라 다음 장이 미리 보이거나 잘린다.
 */
function Scene({
  id,
  label,
  eyebrow,
  title,
  children,
}: {
  id?: string
  label: string
  eyebrow: string
  title: ReactNode
  children: ReactNode
}) {
  return (
    <section
      id={id}
      aria-label={label}
      className="lp-snap relative flex min-h-dvh w-full flex-col items-center justify-center gap-10 overflow-hidden px-5 py-16 sm:px-8 lg:gap-20 lg:px-14"
    >
      <header className="relative z-[1] flex flex-col gap-3 text-center lg:gap-4">
        {/* 번호는 장식이 아니라 순서다. 세 장이 한 흐름이라는 것을 이것으로 읽는다. */}
        <p className="text-[22px] font-extrabold tracking-[0.2em] text-white/65 lg:text-[23px]">
          {eyebrow}
        </p>
        <h2 className="m-0 text-[27px] leading-[1.14] font-[750] tracking-[-0.04em] break-keep text-balance text-white sm:text-[38px] lg:text-[54px]">
          {title}
        </h2>
      </header>
      {children}
    </section>
  )
}

export function ServiceIntro({ footer }: { footer?: ReactNode }) {
  return (
    <>
      {/*
        01 · 무엇을 읽는가.

        `id`는 헤더 내비게이션의 `서비스 소개`가 가리키는 곳이다. 티켓 246이 그 해시를
        `shared/config/primaryNav`의 `SERVICE_INTRO_HASH`로 옮겨 랜딩 헤더와 로그인
        이후 헤더가 같은 값을 쓴다. 둘 중 하나만 바꾸면 그 링크가 아무 데도 가지 않는다.
      */}
      <Scene
        id="service-intro"
        label="내 GitHub를 읽는 방법"
        eyebrow="01"
        title={
          <>
            내 GitHub를 보고,
            <br />
            내가 해온 경험을 파악합니다
          </>
        }
      >
        <div className="relative z-[1] grid w-full max-w-[1000px] items-center gap-9 lg:grid-cols-[minmax(0,320px)_1fr_170px_1fr_minmax(0,320px)] lg:gap-0">
          <div className="mx-auto flex w-full max-w-[360px] flex-col gap-3 lg:mx-0 lg:max-w-none">
            {REPO_ROWS.map((row, index) => (
              <div
                key={row.key}
                className={`lp-bob flex items-center gap-3.5 rounded-[18px] border border-white/50 bg-white/[0.16] px-5 py-[18px] backdrop-blur-[18px] ${row.indent ? 'lg:ml-[26px]' : ''}`}
                /* 카드마다 1초씩 어긋내지 않으면 세 장이 한 덩어리로 같이 떠오른다. */
                style={{ '--lp-delay': `${index}s` } as CSSProperties}
              >
                <RepoIcon className="h-7 w-7 shrink-0 text-white" />
                <span className="flex flex-1 flex-col gap-[7px]">
                  <i className="block h-[9px] rounded-md bg-white/85" style={{ width: row.name }} />
                  <i className="block h-[7px] rounded-md bg-white/40" style={{ width: row.meta }} />
                </span>
              </div>
            ))}
          </div>

          <FlowConnector direction="out" className="hidden lg:mx-[18px] lg:block" />

          {/* 판정. 화면에서 가장 진한 덩어리라 시선이 여기서 한 번 멈춘다. */}
          <div className="relative mx-auto grid h-[130px] w-[130px] place-items-center lg:h-[170px] lg:w-[170px]">
            <i
              aria-hidden="true"
              className="lp-pulse absolute -inset-[30px] rounded-full bg-[radial-gradient(circle,rgba(91,141,255,.55),transparent_70%)] blur-[22px]"
            />
            {/* 링 둘을 절반씩 어긋내면 하나가 사라질 때 다음이 이미 퍼지고 있다. */}
            <i
              aria-hidden="true"
              className="lp-ring absolute inset-0 rounded-full border-[1.5px] border-[rgba(145,189,255,0.6)]"
            />
            <i
              aria-hidden="true"
              className="lp-ring absolute inset-0 rounded-full border-[1.5px] border-[rgba(145,189,255,0.6)]"
              style={{ '--lp-delay': '1300ms' } as CSSProperties}
            />
            <span className="relative grid h-[112px] w-[112px] place-items-center rounded-full border border-[rgba(145,189,255,0.45)] bg-[linear-gradient(160deg,#233A6B,#101A2E)] shadow-[0_26px_60px_rgba(16,26,46,0.45)] lg:h-[150px] lg:w-[150px]">
              <SearchIcon className="h-11 w-11 text-white lg:h-[60px] lg:w-[60px]" />
            </span>
          </div>

          <FlowConnector direction="in" delay="900ms" className="hidden lg:mx-[18px] lg:block" />

          {/*
            결과. 막대 길이는 값이 아니라 "기술마다 쌓인 깊이가 다르다"는 모양이다.
            숫자를 붙이지 않는 이유는 로그인 전이라 조회한 적 없는 값이기 때문이다.
          */}
          <div className="mx-auto flex w-full max-w-[360px] flex-col gap-5 rounded-[26px] border border-white/90 bg-white/[0.88] px-[30px] py-7 text-[#101A2E] shadow-[0_28px_60px_rgba(23,45,83,0.2)] lg:mx-0 lg:max-w-none">
            <span className="text-[20px] font-extrabold tracking-[-0.03em] lg:text-[24px]">
              내가 해온 경험
            </span>
            <div className="flex flex-col gap-3.5">
              {EVIDENCE_BARS.map((width) => (
                <span key={width} className="block h-3.5 overflow-hidden rounded-lg bg-[#EAF1FF]">
                  <i
                    className="block h-full rounded-lg bg-[linear-gradient(90deg,#2F5EEB,#5B8DFF)]"
                    style={{ width }}
                  />
                </span>
              ))}
            </div>
          </div>
        </div>
      </Scene>

      {/* 02 · 그것이 무엇과 만나는가 */}
      <Scene label="채용시장과의 대조" eyebrow="02" title="내 경험이 채용시장과 만납니다">
        <div
          aria-hidden="true"
          className="lp-orb-drift pointer-events-none absolute top-[10%] right-[-20%] h-[360px] w-[360px] rounded-full bg-[radial-gradient(circle,rgba(125,155,197,.55),transparent_70%)] blur-[46px] lg:right-[-6%] lg:h-[560px] lg:w-[560px]"
          style={{ '--lp-duration': '10s' } as CSSProperties}
        />

        <div className="relative z-[1] grid w-full max-w-[880px] gap-5 sm:grid-cols-2 lg:gap-10">
          {MARKET_CARDS.map((card) => {
            const solid = card.tone === 'solid'
            return (
              <div
                key={card.key}
                className={`flex flex-col justify-between gap-8 rounded-[30px] px-8 py-9 lg:h-[300px] lg:px-9 lg:py-10 ${
                  solid
                    ? 'border border-white/90 bg-white/[0.88] text-[#101A2E] shadow-[0_28px_60px_rgba(23,45,83,0.2)]'
                    : 'border-[1.5px] border-dashed border-white/70 bg-white/[0.14] text-white backdrop-blur-[18px]'
                }`}
              >
                <span
                  className={`grid h-14 w-14 place-items-center rounded-[20px] lg:h-16 lg:w-16 ${
                    solid
                      ? 'bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] text-white shadow-[0_10px_24px_rgba(47,94,235,0.35)]'
                      : 'border border-white/60 bg-white/[0.22] text-white'
                  }`}
                >
                  {solid ? (
                    <BriefcaseIcon className="h-7 w-7 lg:h-8 lg:w-8" />
                  ) : (
                    <ArrowUpIcon className="h-7 w-7 lg:h-8 lg:w-8" />
                  )}
                </span>
                <div className="flex flex-col gap-2">
                  {/*
                    줄바꿈이 데이터에 들어 있다(`\n`). 카드 두 장의 제목 높이를 맞추려고
                    디자인이 정한 자리라 여기서 임의로 흘리지 않는다.
                  */}
                  <span className="text-[24px] leading-[1.15] font-extrabold tracking-[-0.035em] break-keep whitespace-pre-line lg:text-[30px]">
                    {card.title}
                  </span>
                  <span
                    className={`text-[15px] break-keep lg:text-[17px] ${solid ? 'text-[#5F6F86]' : 'text-white/80'}`}
                  >
                    {card.body}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </Scene>

      {/* 03 · 다음에 무엇을 하는가 */}
      <Scene label="다음 준비" eyebrow="03" title="다음으로 무엇을 준비할까요?">
        <div className="relative z-[1] flex w-full max-w-[1000px] flex-wrap items-center justify-center gap-x-8 gap-y-8 lg:grid lg:grid-cols-[auto_1fr_auto_1fr_auto] lg:items-end lg:gap-0">
          {NEXT_STEPS.map((step, index) => (
            <Fragment key={step.key}>
              {index > 0 ? (
                <FlowConnector
                  direction={index === 1 ? 'out' : 'in'}
                  delay={`${index * 900 - 900}ms`}
                  className="hidden lg:mx-[26px] lg:mb-[52px] lg:block lg:self-end"
                />
              ) : null}

              {step.key === 'now' ? (
                <FlowNode
                  tone="solid"
                  label={step.label}
                  circleClassName="h-[88px] w-[88px] lg:h-[120px] lg:w-[120px]"
                  icon={<LayersIcon className="h-8 w-8 lg:h-[46px] lg:w-[46px]" />}
                />
              ) : null}

              {step.key === 'learn' ? (
                <FlowNode
                  tone="dark"
                  label={step.label}
                  ring
                  circleClassName="h-[112px] w-[112px] lg:h-[160px] lg:w-[160px]"
                  icon={<CompassIcon className="h-11 w-11 lg:h-16 lg:w-16" />}
                />
              ) : null}

              {step.key === 'wider' ? (
                /*
                  마지막 단계만 크고 동심원을 겹친다. 추천이 점수가 아니라 선택지를
                  넓히는 일이라는 것을 크기와 퍼짐으로 말한다.
                */
                <FlowNode
                  tone="glass"
                  label={step.label}
                  circleClassName="h-[150px] w-[150px] lg:h-[220px] lg:w-[220px]"
                  icon={<BriefcaseIcon className="h-9 w-9 text-[#2F5EEB] lg:h-[50px] lg:w-[50px]" />}
                >
                  <i
                    aria-hidden="true"
                    className="absolute inset-[16px] rounded-full border border-white/50 lg:inset-[22px]"
                  />
                  <i
                    aria-hidden="true"
                    className="absolute inset-[32px] rounded-full bg-white/[0.86] shadow-[0_12px_30px_rgba(23,45,83,0.18)] lg:inset-[46px]"
                  />
                </FlowNode>
              ) : null}
            </Fragment>
          ))}
        </div>
      </Scene>

      {/*
        마지막 장 · 시작 지점과 하단바.

        하단바를 이 장 **안에** 넣는다 · 티켓 320. `ServiceIntro` 뒤에 꼬리로 두면
        데스크톱에서 읽을 수 없다 — `landing.css`가 1024px·640px 이상에서 스크롤
        컨테이너에 `scroll-snap-type: y mandatory`를 걸어 두었고, 스냅 지점이 없는
        꼬리 요소는 가장 가까운 스냅 지점(이 장의 시작)으로 되돌아간다.

        그렇다고 하단바에 `lp-snap`과 `min-h-dvh`를 줘서 장을 하나 더 만들면, 사이트
        정보가 콘텐츠 한 장처럼 읽힌다. 마지막 CTA를 지나 빈 화면이 한 번 더 나오고
        스크롤이 거기서 또 멈춘다.

        그래서 이 장 하나를 **뷰포트보다 크게** 만든다. 스냅 영역이 스냅포트보다 크면
        그 안의 어느 위치에서든 멈출 수 있다(CSS Scroll Snap). 스냅 지점은 이 장의
        시작 하나뿐이라 CTA는 정가운데에 그대로 오고, 그 아래로는 자유 스크롤이라
        하단바가 이어져 보인다.

        CTA의 가운데는 **안쪽 래퍼**가 `min-h-dvh`를 갖게 해서 지킨다. 바깥 섹션에
        주고 `flex-1`로 나눠 가지면 가운데가 뷰포트가 아니라 "하단바를 뺀 나머지"의
        가운데가 되어 하단바 높이의 절반만큼 위로 밀린다.
      */}
      <section aria-label="시작하기" className="lp-snap relative w-full">
        <div className="relative flex min-h-dvh w-full flex-col items-center justify-center overflow-hidden px-5 py-14 sm:px-8 lg:px-14">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-1/2 h-[300px] w-[560px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(ellipse,rgba(91,141,255,.32),transparent_70%)] blur-[60px] lg:h-[420px] lg:w-[900px]"
          />

          <div className="relative z-[1] flex w-full max-w-[820px] flex-col items-center gap-7 text-center">
            <h2 className="m-0 text-[30px] leading-[1.14] font-extrabold tracking-[-0.045em] break-keep text-balance text-white sm:text-[42px] lg:text-[60px]">
              내 GitHub에는
              <br />
              어떤 가능성이 있을까요?
            </h2>

            <AnalysisStartLink
              className="inline-flex items-center gap-3 rounded-2xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-8 py-[18px] text-[17px] font-bold text-white shadow-[0_18px_40px_rgba(31,60,140,0.4)] transition-shadow hover:shadow-[0_22px_48px_rgba(31,60,140,0.48)] lg:px-[38px] lg:py-[22px] lg:text-[19px]"
            >
              <GithubIcon className="h-[22px] w-[22px] lg:h-6 lg:w-6" />
              GitHub로 분석 시작하기
            </AnalysisStartLink>

            {/* 하지 않는 것을 마지막에 한 번 더 적는다. 권한을 넘기기 직전이라 여기가 맞다. */}
            <span className="text-[14px] text-white/70 lg:text-[15px]">
              읽기 전용 · 선택한 저장소만 분석합니다
            </span>
          </div>
        </div>

        {/*
          하단바는 앞 화면 아래에 그대로 이어 붙는다. 자기 높이만 쓰므로 한 장으로
          읽히지 않고, 이 섹션 안에 있어 스냅이 걸린 화면에서도 도달할 수 있다.

          좌우 여백을 여기서 주지 않는다. `SiteFooter`가 이미 `max-w-[1520px]`
          컨테이너와 `px-5 sm:px-8 lg:px-12`를 갖고 있어, 감싸면서 한 번 더 주면
          같은 여백이 두 번 들어간다.
        */}
        {footer !== undefined ? <div className="relative z-[1] w-full">{footer}</div> : null}
      </section>
    </>
  )
}
