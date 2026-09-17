import type { CSSProperties } from 'react'
import { Link } from 'react-router'
import { SiteHeader } from '@/app/layouts/SiteHeader'
import { AnalysisStartLink } from '@/features/landing/components/AnalysisStartLink'
import { ROLE_FIT, ROLE_FITS } from '@/features/landing/roleFitData'
import type { RoleKey } from '@/features/landing/roleFitData'

/**
 * 랜딩 첫 장 · 직무를 고르면 그 직무의 절반이 채워진다.
 *
 * 이 화면의 요점은 **비대칭**이다. 왼쪽(시장)은 Registry에서 온 진짜 값으로 차 있고,
 * 오른쪽(내 근거)은 비어 있다. 로그인 전에는 사용자 데이터가 없으므로 그 칸을 지어낸
 * 숫자로 채우는 대신 비워 두고, 그 빈칸이 그대로 CTA의 이유가 된다.
 *
 * 직무 선택을 이 장 안에 둔 이유는 스크롤 스냅 때문이다. 칩을 다른 장에 두면 고른
 * 결과가 화면 밖에서 바뀌어 무엇이 달라졌는지 보이지 않는다.
 */
export function RoleFitScene({
  role,
  onRoleChange,
}: {
  role: RoleKey
  onRoleChange: (next: RoleKey) => void
}) {
  const active = ROLE_FIT[role]
  const rest = active.total - active.techs.length

  return (
    <section
      aria-label="직무별 기술 판정 범위"
      className="lp-snap relative flex min-h-dvh w-full flex-col overflow-hidden px-5 sm:px-8 lg:px-14"
    >
      <div
        aria-hidden="true"
        className="lp-drift pointer-events-none absolute -top-[180px] right-[-120px] h-[420px] w-[420px] rounded-full bg-[radial-gradient(circle_at_42%_42%,rgba(125,155,197,.9),rgba(125,155,197,.5)_46%,transparent_72%)] blur-[40px] lg:right-[60px] lg:h-[620px] lg:w-[620px]"
      />

      <div className="relative z-[4] mx-auto flex w-full max-w-[1440px] flex-1 flex-col">
        <SiteHeader variant="landing" />

        <div className="grid flex-1 items-center gap-8 pt-4 pb-8 lg:grid-cols-[46%_54%] lg:gap-10 lg:pt-0 lg:pb-10">
          {/* ── 왼쪽 · 무엇을 묻는 서비스인가 ── */}
          <div>
            <div
              className="lp-rise mb-4 text-[12px] font-extrabold tracking-[0.22em] text-white/75 lg:mb-5 lg:text-[13px]"
              style={{ '--lp-delay': '60ms' } as CSSProperties}
            >
              ROLE FIT
            </div>

            <h1
              className="lp-rise m-0 text-[32px] leading-[1.12] font-extrabold tracking-[-0.05em] break-keep text-white [text-shadow:0_8px_28px_rgba(25,37,67,0.14)] sm:text-[38px] lg:text-[46px]"
              style={{ '--lp-delay': '140ms' } as CSSProperties}
            >
              이 직무가 요구하는 기술,
              <br />내{' '}
              <span className="bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] bg-clip-text text-transparent [text-shadow:none]">
                GitHub
              </span>
              는 무엇을 증명할까요
            </h1>

            <p
              className="lp-rise mt-4 mb-7 max-w-[470px] text-[15px] leading-[1.7] break-keep text-white/90 lg:text-[18px]"
              style={{ '--lp-delay': '240ms' } as CSSProperties}
            >
              직무를 고르면 GitJob이 판정하는 기술을 보여드립니다. 오른쪽 빈칸은 저장소를
              분석한 뒤 <strong className="font-bold text-white">당신의 근거</strong>로 채워집니다.
            </p>

            <div
              className="lp-rise flex flex-wrap gap-3"
              style={{ '--lp-delay': '330ms' } as CSSProperties}
            >
              <AnalysisStartLink
                className="rounded-xl bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-[26px] py-4 text-[16px] font-bold text-white shadow-[0_14px_30px_rgba(31,60,140,0.34)] transition-shadow hover:shadow-[0_18px_38px_rgba(31,60,140,0.42)]"
              >
                내 근거 채우러 가기
              </AnalysisStartLink>
              {/*
                로그인 전에 열리는 유일한 제품 화면이 트렌드다. 공고 매칭·Evidence는
                분석 결과가 있어야 채워지므로 둘러보기의 목적지가 될 수 없다.
              */}
              <Link
                to="/trends"
                className="rounded-xl border border-white/35 bg-white/10 px-6 py-4 text-[16px] font-bold text-white backdrop-blur-[14px] transition-colors hover:bg-white/20"
              >
                기술 트렌드 먼저 보기
              </Link>
            </div>
          </div>

          {/* ── 오른쪽 · 시장 절반은 채워져 있고 내 절반은 비어 있다 ── */}
          <div
            className="lp-panel-in rounded-[26px] border border-white/45 bg-white/[0.14] p-5 shadow-[0_24px_60px_rgba(23,45,83,0.2)] backdrop-blur-[20px] lg:p-6"
            style={{ '--lp-delay': '260ms' } as CSSProperties}
          >
            {/*
              `radiogroup`이 아니라 버튼 목록인 이유는 이것이 폼 입력이 아니라 화면
              내용을 바꾸는 조작이기 때문이다. 제출할 값이 없다.
            */}
            <div className="flex flex-wrap gap-2" role="group" aria-label="직무 선택">
              {ROLE_FITS.map((item) => {
                const on = item.key === role
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => onRoleChange(item.key)}
                    aria-pressed={on}
                    className={`rounded-full px-4 py-2 text-[13.5px] font-bold transition-colors ${
                      on
                        ? 'bg-white text-[#14213D] shadow-[0_8px_20px_rgba(23,45,83,0.22)]'
                        : 'border border-white/40 bg-white/10 text-white/85 hover:bg-white/20'
                    }`}
                  >
                    {item.label}
                  </button>
                )
              })}
            </div>

            <div className="mt-5 flex items-baseline justify-between gap-3">
              <span className="text-[15px] font-bold text-white lg:text-[17px]">
                {active.label} · {active.summary}
              </span>
              {/* 이 수는 Registry에서 실제로 센 값이다. 조회가 필요 없어 로그인 전에도 참이다. */}
              <span className="text-[13px] text-white/70">
                판정 가능 기술 <strong className="font-bold text-white">{active.total}</strong>개
              </span>
            </div>

            <div className="mt-4 grid grid-cols-[1fr_auto] items-center gap-x-3 text-[11px] font-extrabold tracking-[0.14em] text-white/55">
              <span>이 직무의 기술</span>
              <span>내 근거</span>
            </div>

            <ul className="mt-2 flex flex-col gap-1.5">
              {active.techs.map((tech, index) => (
                <li
                  key={tech}
                  className="grid grid-cols-[1fr_auto] items-center gap-x-3 rounded-xl border border-white/25 bg-white/[0.09] px-4 py-2"
                >
                  <span className="truncate text-[14.5px] font-semibold text-white">{tech}</span>
                  {/*
                    빈칸이 이 화면의 메시지다. `—`나 `0`을 넣으면 "없음"을 판정한 것이
                    되는데, 아직 아무것도 분석하지 않았으므로 판정한 적이 없다.
                    점선은 채워질 자리라는 표시다.
                  */}
                  <span
                    className="lp-bob rounded-md border border-dashed border-white/40 px-2.5 py-1 text-[11.5px] font-bold text-white/50"
                    style={{ '--lp-delay': `${index * 220}ms` } as CSSProperties}
                  >
                    비어 있음
                  </span>
                </li>
              ))}
            </ul>

            {rest > 0 ? (
              <p className="mt-3 text-[12.5px] text-white/60">
                외 {rest}개를 같은 기준으로 판정합니다.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  )
}
