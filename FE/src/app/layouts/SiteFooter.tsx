import { Link } from 'react-router'
import { PROJECT_CODE, TEAM_EMAIL, TEAM_NAME } from '@/shared/constants/team'

/**
 * 서비스 하단바.
 *
 * 두 곳이 쓴다 — 로그인 이후 셸(`AppLayout`)과 랜딩 마지막 장(`ServiceIntro`).
 * 링크와 문구가 같아야 해서 컴포넌트 하나를 `tone`으로 갈라 쓴다. 파일을 둘로
 * 나누면 처리방침 링크가 한쪽에만 추가되는 일이 생긴다.
 *
 * `tone`이 필요한 이유는 배경이 정반대이기 때문이다. 앱 셸은 밝은 배경 위 진한
 * 글씨(`AppLayout`의 `APP_BACKDROP`)이고, 랜딩은 짙은 그라데이션 위 흰 글씨다
 * (`LandingPage`의 `BACKDROP`). 같은 색을 쓰면 한쪽에서 반드시 읽히지 않는다.
 *
 * 담는 것은 **확인된 사실만**이다. 팀 이름·팀 메일·처리방침·팀 소개, 그리고 SSAFY
 * 교육 프로젝트라는 사실. 사업자 정보나 대표 전화처럼 존재하지 않는 항목을
 * 형식만 맞추려고 넣지 않는다.
 *
 * 소셜 아이콘도 두지 않았다. 팀 계정이 없어서 연결할 곳이 없고, 누를 수 있는데
 * 아무 일도 없는 것을 만들지 않는다(Interaction Safety, `Scaffold.tsx`).
 */

/**
 * 하단바가 갖는 링크.
 *
 * 두 항목 모두 실제 라우트가 있다(`app/router.tsx`). 먼저 만들어 두고 나중에
 * 화면을 붙이는 순서로는 하지 않았다 — 그 사이 동안 링크가 404가 된다.
 */
const LINKS: ReadonlyArray<{ to: string; label: string }> = [
  { to: '/privacy', label: '개인정보 처리방침' },
  { to: '/team', label: '팀 소개' },
]

type Tone = 'light' | 'onDark'

/** 톤별 색. 값을 호출부에 흩지 않고 여기서만 고른다. */
const TONE = {
  light: {
    frame: 'border-t border-brand-line',
    brand: 'text-brand-ink',
    body: 'text-brand-muted',
    faint: 'text-brand-faint',
    link: 'text-brand-body hover:text-brand-ink',
    divider: 'bg-brand-line',
  },
  onDark: {
    frame: 'border-t border-white/20',
    brand: 'text-white',
    body: 'text-white/70',
    faint: 'text-white/55',
    link: 'text-white/75 hover:text-white',
    divider: 'bg-white/25',
  },
} as const satisfies Record<Tone, Record<string, string>>

export function SiteFooter({ tone = 'light' }: { tone?: Tone }) {
  const c = TONE[tone]

  return (
    <footer className={`w-full ${c.frame}`}>
      {/*
        폭은 `.gj-shell`(1520px)과 같은 기준선을 쓴다. 앱 셸 안에서 본문보다 넓거나
        좁으면 하단바만 어긋나 보인다. 랜딩은 본문이 1440px이라 조금 좁은데, 하단바는
        가운데 정렬이라 그 차이가 드러나지 않는다.
      */}
      <div className="mx-auto w-full max-w-[1520px] px-5 py-10 sm:px-8 lg:px-12">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className={`text-[15px] font-[750] tracking-[-0.02em] ${c.brand}`}>GitJob</p>
            <p className={`mt-2 text-[13px] leading-[1.7] break-keep ${c.body}`}>
              GitHub 저장소에서 기술 사용 근거를 찾아 목표 직무의 채용 수요와 비교합니다.
            </p>
            <p className={`mt-1 text-[12px] leading-[1.7] ${c.faint}`}>
              SSAFY 15기 자율 프로젝트 · {PROJECT_CODE}
            </p>
          </div>

          {/*
            링크와 연락처. 좁은 화면에서는 위 소개 아래로 쌓이고, lg 이상에서 오른쪽에
            붙는다. `<nav>`로 감싸는 것은 스크린 리더가 본문과 구분해 건너뛸 수 있게
            하기 위해서다.
          */}
          <div className="flex flex-col gap-5 sm:flex-row sm:gap-12 lg:shrink-0">
            <nav aria-label="하단 메뉴">
              <ul className="flex flex-col gap-2.5">
                {LINKS.map((link) => (
                  <li key={link.to}>
                    <Link
                      to={link.to}
                      className={`text-[13px] font-medium transition-colors ${c.link}`}
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>

            <div>
              <p
                className={`text-[10.5px] font-extrabold tracking-[0.12em] ${c.faint}`}
              >
                CONTACT
              </p>
              {/*
                `mailto:`인 것은 이 주소가 문의를 실제로 받는 창구이기 때문이다. 복사만
                가능한 텍스트로 두면 개인정보 열람·삭제 요청 경로가 한 단계 멀어진다.
              */}
              <a
                href={`mailto:${TEAM_EMAIL}`}
                className={`mt-2 block text-[13px] font-medium transition-colors ${c.link}`}
              >
                {TEAM_EMAIL}
              </a>
              <p className={`mt-1 text-[12px] ${c.faint}`}>{TEAM_NAME}</p>
            </div>
          </div>
        </div>

        <div className={`mt-8 h-px w-full ${c.divider}`} />

        {/*
          저작권 줄. 연도를 `new Date()`로 만들지 않는다 — 렌더 시점에 따라 값이
          달라져 스크린샷·테스트가 흔들리고, 실제로 바뀌어야 하는 값도 아니다.
        */}
        <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <p className={`text-[12px] ${c.faint}`}>© 2026 {TEAM_NAME}</p>
          <span className={`text-[12px] ${c.faint}`} aria-hidden>
            ·
          </span>
          <p className={`text-[12px] ${c.faint}`}>
            교육 목적으로 만든 프로젝트이며 상용 서비스가 아닙니다.
          </p>
        </div>
      </div>
    </footer>
  )
}
