import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router'
import { githubLoginUrl } from '@/features/auth/api/authUrls'
import {
  EVIDENCE_AXES,
  EVIDENCE_LADDER,
  INTRO_STEPS,
} from '@/features/landing/serviceIntroData'

/**
 * 랜딩 스크롤 아래의 서비스 소개 · 티켓 S15P21E102-212.
 *
 * Hero 아래로 두 장이 이어지고 마지막에 시작 지점을 준다. 한 번 굴리면 한 장씩
 * 넘어가도록 각 섹션이 `lp-snap`을 갖는다(스냅 규칙은 `landing.css`).
 *
 * 배경은 그리지 않는다. `LandingPage`의 스크롤 컨테이너가 그라데이션을 한 장 깔고
 * 모든 섹션이 그 위를 지나간다. 섹션마다 배경을 주면 이음매가 보인다.
 *
 * 시각 규약은 Hero와 같다 — 유리 패널(`bg-white/12` + `backdrop-blur`), 흰 글씨,
 * `lp-rise` 등장. Final v2의 로그인 이후 화면들이 쓰는 밝은 카드 톤을 여기 가져오면
 * 랜딩 배경 위에서 대비가 무너진다.
 *
 * 문구는 전부 화면 각주에서 왔다(`serviceIntroData` 주석의 출처 목록).
 */

/**
 * 제목 안에서 하늘색으로 칠하는 낱말.
 *
 * 색은 Hero가 `GitHub` 한 단어에 쓰는 `#91BDFF`와 같은 값이다. 제목마다 제품의
 * 이름(`GitHub`·`Evidence`)과 핵심어(`근거`)만 칠해서, 문장을 다 읽지 않아도 그 장이
 * 무엇에 관한 것인지 먼저 보이게 한다. 나머지는 흰색이다.
 */
function Sky({ children }: { children: ReactNode }) {
  return <span className="text-[#91BDFF]">{children}</span>
}

/**
 * 배경의 흐릿한 빛 덩어리 · 티켓 212.
 *
 * Hero가 이미 쓰는 장식과 같은 종류다 — 큰 원에 radial-gradient를 채우고 blur를
 * 세게 먹인 것. 윤곽이 없어서 섹션 경계에서 잘려도 단면이 보이지 않는다.
 *
 * 처음에는 Hero처럼 테두리만 남긴 가는 호를 깔았다가 걷어냈다. 매끈한 배경 위의
 * 1px 실선은 장식이 아니라 화면에 붙은 머리카락처럼 보였고, 장이 바뀔 때 잘린
 * 단면이 그대로 드러났다(2026-09-11 피드백). 자세한 근거는 `landing.css`의
 * `lp-glow-drift` 주석에 남겼다.
 */
function Glow({
  box,
  tint,
  duration,
  delay = '0ms',
}: {
  box: string
  tint: string
  duration: string
  delay?: string
}) {
  return (
    <div className={`absolute ${box}`}>
      <div
        className={`lp-glow-drift h-full w-full rounded-full ${tint}`}
        style={{ '--lp-duration': duration, '--lp-delay': delay } as CSSProperties}
      />
    </div>
  )
}

/** Hero 배경에서 가져온 두 색. 파랑은 오른쪽 빛, 모래빛은 왼쪽 아래 빛이다. */
const TINT_BLUE =
  'bg-[radial-gradient(circle_at_42%_42%,rgba(125,155,197,.55),rgba(125,155,197,.28)_46%,transparent_72%)] blur-[46px]'
const TINT_SAND =
  'bg-[radial-gradient(circle,rgba(212,181,162,.42),transparent_70%)] blur-[42px]'

/**
 * 장마다 다른 빛 배치.
 *
 * 자리와 주기를 어긋내 스크롤할 때 배경이 바뀐 것이 보이게 한다. 덩어리의 중심은
 * 본문에서 떨어뜨려 글자 뒤가 밝아지지 않게 뒀다.
 */
function SectionGlow({ variant }: { variant: 1 | 2 | 3 }) {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {variant === 1 && (
        <>
          <Glow
            box="top-[4%] right-[2%] h-[560px] w-[560px]"
            tint={TINT_BLUE}
            duration="5s"
          />
          <Glow
            box="bottom-[2%] left-[-6%] h-[440px] w-[440px]"
            tint={TINT_SAND}
            duration="7s"
            delay="-5s"
          />
        </>
      )}

      {variant === 2 && (
        <>
          <Glow
            box="top-[-6%] left-[8%] h-[520px] w-[520px]"
            tint={TINT_SAND}
            duration="5.5s"
          />
          <Glow
            box="right-[-4%] bottom-[-8%] h-[600px] w-[600px]"
            tint={TINT_BLUE}
            duration="4.5s"
            delay="-6s"
          />
        </>
      )}

      {variant === 3 && (
        <>
          <Glow
            box="top-[10%] left-[-8%] h-[500px] w-[500px]"
            tint={TINT_BLUE}
            duration="5.2s"
          />
          <Glow
            box="right-[4%] bottom-[6%] h-[460px] w-[460px]"
            tint={TINT_SAND}
            duration="7.2s"
            delay="-4s"
          />
        </>
      )}
    </div>
  )
}

/** 섹션 공통 골격. 전체 높이를 채우고 가운데 정렬한다. */
function IntroSection({
  id,
  eyebrow,
  title,
  label,
  lead,
  variant,
  children,
}: {
  id?: string
  eyebrow: string
  /** 강조 span을 담을 수 있어야 해서 문자열이 아니다. */
  title: ReactNode
  /** 스크린리더용 섹션 이름. `title`에서 마크업을 걷어낸 문장이다. */
  label: string
  lead?: string
  variant: 1 | 2 | 3
  children: ReactNode
}) {
  return (
    <section
      id={id}
      aria-label={label}
      className="lp-snap relative flex min-h-dvh w-full items-center overflow-hidden px-5 py-20 sm:px-8 lg:px-14"
    >
      <SectionGlow variant={variant} />
      {/* 빛 위에 본문을 얹는다. */}
      <div className="relative z-[1] mx-auto w-full max-w-[1180px]">
        <p className="text-[11px] font-extrabold tracking-[0.18em] text-white/65">{eyebrow}</p>
        {/*
          폭을 제한하지 않는다. `max-w-[22ch]`를 두었더니 46px 제목에서 550px쯤에서
          잘려 두 줄이 됐고, 한국어는 기본적으로 글자 단위로 접히므로 `시작합니다`가
          `시 / 작합니다`로 갈라졌다.

          `break-keep`(word-break: keep-all)으로 낱말 중간에서 접지 않게 한다. 좁은
          화면에서 두 줄이 되더라도 낱말은 온전히 남고, `text-balance`가 두 줄의
          길이를 비슷하게 맞춘다.
        */}
        <h2 className="mt-3 text-[32px] leading-[1.15] font-[750] tracking-[-0.04em] break-keep text-balance text-white sm:text-[40px] lg:text-[46px]">
          {title}
        </h2>
        {lead !== undefined && (
          <p className="mt-5 max-w-[62ch] text-[15px] leading-[1.75] break-keep text-white/80 lg:text-base">
            {lead}
          </p>
        )}
        <div className="mt-10">{children}</div>
      </div>
    </section>
  )
}

/** 유리 카드. Hero의 미리보기 패널과 같은 표면을 쓴다. */
const GLASS =
  'rounded-[22px] border border-white/35 bg-white/[0.12] p-6 backdrop-blur-[18px] shadow-[0_18px_44px_rgba(23,45,83,0.18)] lg:p-7'

/**
 * @param footer 마지막 장 아래에 붙일 하단바. 아래 마지막 장 주석 참고.
 */
export function ServiceIntro({ footer }: { footer?: ReactNode }) {
  return (
    <>
      <IntroSection
        id="service-intro"
        eyebrow="HOW IT WORKS"
        title={
          <>
            <Sky>GitHub</Sky>에 이미 있는 <Sky>근거</Sky>로 시작합니다
          </>
        }
        label="GitHub에 이미 있는 근거로 시작합니다"
        variant={1}
        lead="이력서에 적은 기술 대신, 저장소에서 실제로 확인되는 근거를 씁니다. 세 단계로 이어집니다."
      >
        <ol className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {INTRO_STEPS.map((item, index) => (
            <li
              key={item.step}
              className={`lp-rise flex flex-col ${GLASS}`}
              style={{ '--lp-delay': `${index * 90}ms` } as CSSProperties}
            >
              <span
                aria-hidden
                className="grid size-9 place-items-center rounded-xl bg-white/85 text-[13px] font-extrabold text-[#2F5EEB]"
              >
                {item.step}
              </span>
              <h3 className="mt-5 text-[19px] leading-[1.3] font-[750] tracking-[-0.02em] text-white">
                {item.title}
              </h3>
              <p className="mt-3 flex-1 text-[14px] leading-[1.7] text-white/80">{item.body}</p>
              <Link
                to={item.to}
                className="mt-6 inline-flex w-fit items-center gap-1.5 rounded-xl border border-white/40 bg-white/10 px-4 py-2.5 text-[13px] font-bold text-white transition-colors hover:bg-white/20"
              >
                {item.linkLabel}
                <span aria-hidden>→</span>
              </Link>
            </li>
          ))}
        </ol>
      </IntroSection>

      <IntroSection
        eyebrow="EVIDENCE"
        title={
          <>
            <Sky>Evidence</Sky>는 점수가 아니라 <Sky>근거</Sky>입니다
          </>
        }
        label="Evidence는 점수가 아니라 근거입니다"
        variant={2}
        lead="Level은 숙련도 점수가 아니라 근거가 쌓인 상태입니다. 같은 기술이라도 저장소 기준과 본인 기여 기준을 따로 봅니다."
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_320px]">
          {EVIDENCE_AXES.map((axis, index) => (
            <div
              key={axis.name}
              className={`lp-rise ${GLASS}`}
              style={{ '--lp-delay': `${index * 90}ms` } as CSSProperties}
            >
              <p className="text-[11px] font-extrabold tracking-[0.16em] text-white/65">
                {axis.name.toUpperCase()}
              </p>
              <h3 className="mt-2.5 text-[19px] font-[750] tracking-[-0.02em] text-white">
                {axis.name} Level
              </h3>
              <p className="mt-3 text-[14px] leading-[1.7] text-white/80">{axis.body}</p>
            </div>
          ))}

          {/*
            Level 사다리. 단계 이름만 쓰고 의미 설명은 넣지 않는다. 무엇이 L2인지는
            등급 정책(S15P21E102-127)이 정하며 아직 확정 전이다 —
            `shared/constants/evidenceLevel.ts`가 같은 이유로 설명을 비워 두고 있다.
          */}
          <div
            className={`lp-rise ${GLASS}`}
            style={{ '--lp-delay': '180ms' } as CSSProperties}
          >
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-white/65">LEVEL</p>
            <ol className="mt-4 grid gap-2.5">
              {EVIDENCE_LADDER.map((level, index) => (
                <li key={level} className="flex items-center gap-3">
                  <span className="w-7 shrink-0 font-evidence text-[13px] font-bold text-white">
                    {level}
                  </span>
                  <span aria-hidden className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/20">
                    <span
                      className="block h-full rounded-full bg-white/80"
                      style={{ width: `${((index + 1) / EVIDENCE_LADDER.length) * 100}%` }}
                    />
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-[12.5px] leading-[1.65] text-white/70">
              네 단계는 근거의 누적 상태입니다. 단계별 의미는 등급 정책이 확정되면 화면에
              표시합니다.
            </p>
          </div>
        </div>
      </IntroSection>

      {/*
        마지막 장. 소개를 끝까지 읽은 사람에게 시작 지점을 준다.

        하단바를 이 장 **안에** 넣는다. `ServiceIntro` 뒤에 따로 두면 데스크톱에서
        읽을 수 없다 — `landing.css`가 1024px·700px 이상에서 스크롤 컨테이너에
        `scroll-snap-type: y mandatory`를 걸어 두었고, 스냅 지점이 없는 꼬리 요소는
        가장 가까운 스냅 지점(이 장의 시작)으로 되돌아가 화면에 머물지 않는다.

        그래서 가로 정렬(`items-center`)을 세로(`flex-col`)로 바꾸고, CTA가 남는
        높이를 가운데에서 차지한 뒤 하단바가 그 아래에 놓이게 했다. 스냅 지점은
        이 장 하나 그대로다.
      */}
      <section
        aria-label="시작하기"
        className="lp-snap relative flex min-h-dvh w-full flex-col overflow-hidden px-5 pt-20 sm:px-8 lg:px-14"
      >
        <SectionGlow variant={3} />
        <div className="relative z-[1] mx-auto flex w-full max-w-[820px] flex-1 flex-col justify-center pb-16 text-center">
          <p className="text-[11px] font-extrabold tracking-[0.18em] text-white/65">GET STARTED</p>
          <h2 className="mt-3 text-[32px] leading-[1.15] font-[750] tracking-[-0.04em] break-keep text-balance text-white sm:text-[40px] lg:text-[46px]">
            내 GitHub는 어떤 근거를 갖고 있을까요
          </h2>
          <p className="mx-auto mt-5 max-w-[52ch] text-[15px] leading-[1.75] break-keep text-white/80">
            저장소를 고르면 파일 · 설정 · Commit에서 기술 사용 근거를 찾습니다. 읽기 전용이며
            선택한 저장소만 분석합니다.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            {/*
              Hero의 `GitHub 연동 시작`과 같은 곳으로 간다. 204가 "GitHub Login이
              서비스 진입점"을 Production 계약으로 정했고, 소개를 끝까지 읽은 사람에게
              다른 입구를 주면 흐름이 갈린다.

              `<a>`인 것은 진입 엔드포인트가 302로 GitHub에 넘기기 때문이다. 브라우저
              최상위 이동이어야 하므로 `<Link>`로 부르면 안 된다.
            */}
            <a
              href={githubLoginUrl()}
              className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-[26px] py-4 text-[15px] font-bold text-white shadow-[0_14px_30px_rgba(31,60,140,0.34)] transition-shadow hover:shadow-[0_18px_38px_rgba(31,60,140,0.42)]"
            >
              시작하기
            </a>
            <Link
              to="/trends"
              className="rounded-xl border border-white/35 bg-white/10 px-6 py-4 text-[15px] font-bold text-white backdrop-blur-[14px] transition-colors hover:bg-white/20"
            >
              기술 트렌드 먼저 보기
            </Link>
          </div>
        </div>

        {/* 장식 빛(`SectionGlow`)이 절대 배치라 하단바도 z-index를 올려야 위에 온다. */}
        {footer !== undefined && <div className="relative z-[1] w-full">{footer}</div>}
      </section>
    </>
  )
}
