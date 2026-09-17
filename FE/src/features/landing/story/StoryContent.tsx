import { Link } from 'react-router'
import { useStartPath } from '@/features/landing/story/useStartPath'
import { CountUp } from '@/features/landing/story/CountUp'
import { Rise } from '@/features/landing/story/StoryScene'

/**
 * 다섯 장의 내용 · 확정 디자인 `GitJob Landing Storytelling v2`.
 *
 * <h2>화면 속 숫자에 대하여</h2>
 *
 * 카드의 `87` · `12` · `75%` · `+15` 는 **확정 디자인이 정한 예시**다. 로그인 전
 * 화면이라 조회할 사용자도 Snapshot 도 없어 실제 값을 넣을 자리가 아니다. 제품이
 * 무엇을 하는지 보여주는 한 장면으로 두되, 실제 집계로 바꾸거나 "예시"를 명시하는
 * 결정은 팀에 남긴다(2026-09-17 논의).
 */

export function ProblemScene() {
  const start = useStartPath()

  return (
    <div className="mx-auto flex max-w-[1120px] flex-col items-center gap-7 text-center text-white">
      {/*
        동심원과 떠다니는 빛. 확정 디자인이 첫 장에만 둔 장식이다. 글이 화면 한가운데
        떠 있기만 하면 배경이 그라데이션 한 장으로 보여 깊이가 없다.
      */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        {[1100, 760, 460].map((size, index) => (
          <i
            key={size}
            className="absolute top-1/2 left-1/2 rounded-full border border-white"
            style={{
              width: size,
              height: size,
              marginTop: -size / 2,
              marginLeft: -size / 2,
              opacity: 0.26 + index * 0.06,
            }}
          />
        ))}
        <i className="lp-drift absolute top-[-10%] right-[8%] h-[620px] w-[620px] rounded-full bg-[radial-gradient(circle,rgba(158,184,221,.6),transparent_70%)] blur-[48px]" />
      </div>

      <Rise>
        <h1 className="text-[clamp(44px,5.2vw,80px)] leading-[1.12] font-extrabold tracking-[-0.045em] break-keep [text-shadow:0_10px_32px_rgba(25,37,67,.16)] [text-wrap:balance]">
          변화하는 기술 시장,
          <br />
          나는 무엇을 준비해야 할까?
        </h1>
      </Rise>
      <Rise delay={180}>
        <p className="text-[clamp(17px,1.3vw,21px)] leading-[1.6] break-keep text-white/85">
          공고마다 다른 요구 기술, 매년 바뀌는 우선순위.
          <br />내 GitHub에 남은 근거에서 답을 찾습니다.
        </p>
      </Rise>

      {/*
        첫 화면에 행동할 자리를 둔다. 스토리를 끝까지 내려야 시작 버튼이 나오면, 이미
        무엇인지 아는 사람이 다섯 장을 지나가야 한다. 마지막 장의 CTA 는 "다 읽은 사람"
        을 위한 것이고 이것은 "이미 결정한 사람"을 위한 것이다.
      */}
      <Rise delay={340} className="mt-2 flex flex-col items-center gap-3">
        <Link
          to={start}
          className="inline-flex items-center gap-2.5 rounded-[14px] bg-white px-7 py-4 text-[16px] font-bold text-brand-ink shadow-[0_16px_36px_rgba(25,37,67,.22)] transition-transform hover:-translate-y-0.5"
        >
          <GithubMark className="h-5 w-5" />내 GitHub로 시작하기
        </Link>
        <span className="text-[13px] text-white/70">
          읽기 전용 · 선택한 저장소만 분석합니다
        </span>
      </Rise>
    </div>
  )
}

const EVIDENCE_LEVELS = [
  { level: 'L0', reached: true },
  { level: 'L1', reached: true },
  { level: 'L2', reached: true },
  { level: 'L3', reached: false },
] as const

export function EvidenceScene() {
  return (
    <div className="mx-auto grid w-[min(1120px,88vw)] items-center gap-10 text-white lg:grid-cols-2 lg:gap-[clamp(40px,6vw,96px)]">
      <div className="flex flex-col gap-6">
        <Rise>
        <h2 className="text-[clamp(38px,3.6vw,58px)] leading-[1.14] font-extrabold tracking-[-0.04em] break-keep [text-wrap:balance]">
          Evidence는 점수가 아니라
          <br />
          실제 개발의 근거입니다.
        </h2>
        </Rise>
        <Rise delay={160}>
          <p className="text-[clamp(16px,1.15vw,19px)] leading-[1.65] break-keep text-white/70">
            GitHub의 의존성·설정·소스·빌드 파일에서
            <br />
            실제 사용 흔적을 찾아 기술마다 근거를 남깁니다.
          </p>
        </Rise>
      </div>

      {/* 카드는 글보다 늦게 온다. 무엇을 말하는지 읽은 뒤에 그 증거가 도착한다. */}
      <Rise delay={300} className="flex flex-col gap-6 rounded-[28px] border border-white/15 bg-white/[0.06] px-8 py-7 shadow-[0_30px_80px_rgba(0,0,0,.35),inset_0_1px_0_rgba(255,255,255,.1)] backdrop-blur-[20px]">
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-extrabold tracking-[0.16em] text-[#91BDFF]">
              PERSONAL EVIDENCE
            </span>
            <span className="text-[30px] leading-[1.1] font-extrabold tracking-[-0.03em]">
              Apache Kafka
            </span>
          </div>
          {/* 닿은 등급만 켠다. 네 칸을 다 채우면 이 제품이 등급을 판정한다는 사실이 사라진다. */}
          <div className="flex gap-1.5 pt-1.5">
            {EVIDENCE_LEVELS.map(({ level, reached }, index) => (
              <span
                key={level}
                style={{ '--lp-delay': `${500 + index * 110}ms` } as React.CSSProperties}
                className={`lp-rise grid h-[34px] w-[44px] place-items-center rounded-[10px] border text-[13px] font-extrabold ${
                  reached
                    ? 'border-[#3F73FF] bg-[#2F5EEB] text-white shadow-[0_6px_18px_rgba(47,94,235,.45)]'
                    : 'border-white/15 bg-white/[0.06] text-white/45'
                }`}
              >
                {level}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3.5 rounded-[18px] border border-white/10 bg-[rgba(16,26,46,.6)] px-5 py-5">
          <span className="flex items-center gap-2 text-[14px] font-bold text-white/85">
            <GithubMark className="h-4 w-4" />
            GitJob / main
          </span>
          <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-3 font-evidence text-[15px]">
            <span className="text-white/35">├─</span>
            <span className="truncate text-[#C9DCFF]">build.gradle</span>
            <FileTag>DEPENDENCY</FileTag>
            <span className="text-white/35">└─</span>
            <span className="truncate font-semibold text-white">
              KafkaConfig.java<span className="text-[#91BDFF]">:24</span>
            </span>
            <FileTag active>CONFIG</FileTag>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 text-[14px] text-white/70">
          <span>파일 위치와 본인 Commit까지 연결</span>
          <span className="inline-flex items-center gap-2 font-bold text-white">
            <i className="h-2 w-2 animate-pulse rounded-full bg-[#4ADE80]" />본인 Commit 확인
          </span>
        </div>
      </Rise>
    </div>
  )
}

const JOB_REQUIREMENTS = [
  { name: 'Java', met: true, note: 'L2 · 설정' },
  { name: 'Spring Boot', met: true, note: 'L2 · 설정' },
  { name: 'Apache Kafka', met: true, note: 'L1 · 의존성' },
  { name: 'Kubernetes', met: false, note: '근거 없음' },
] as const

export function JobMatchScene() {
  return (
    <div className="mx-auto grid w-[min(1120px,88vw)] items-center gap-10 text-brand-ink lg:grid-cols-2 lg:gap-[clamp(40px,6vw,96px)]">
      <div className="flex flex-col gap-9">
        <div className="flex flex-col gap-5">
          <Rise>
          <h2 className="text-[clamp(38px,3.6vw,58px)] leading-[1.14] font-extrabold tracking-[-0.04em] break-keep [text-wrap:balance]">
            내가 가진 기술을
            <br />
            실제 채용공고와 비교합니다.
          </h2>
          </Rise>
          <Rise delay={160}>
            <p className="text-[clamp(16px,1.15vw,19px)] leading-[1.65] break-keep text-brand-muted">
              공고의 필수 기술요건과 내 Evidence를 대조합니다.
              <br />
              합격 가능성이 아니라, 요건 일치 여부만 보여드립니다.
            </p>
          </Rise>
        </div>
        <Rise delay={300} className="flex gap-10">
          <Stat value={87} label="전체 백엔드 공고" />
          <span className="w-px bg-[#D6DDE7]" />
          <Stat value={12} label="필수 기술요건 완전 일치" accent />
        </Rise>
      </div>

      <Rise delay={400} className="overflow-hidden rounded-[24px] border border-brand-line bg-white shadow-[0_24px_64px_rgba(23,45,83,.12)]">
        <div className="flex items-start justify-between gap-4 border-b border-[#E8EDF4] px-7 pt-6 pb-5">
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-extrabold tracking-[0.14em] text-brand-faint">
              대표 공고
            </span>
            <span className="text-[22px] font-extrabold tracking-[-0.03em]">
              넥스트레일 백엔드 개발자
            </span>
            <span className="text-[14px] text-brand-faint">서울 · 신입~3년</span>
          </div>
        </div>

        <div className="flex flex-col px-7 py-2">
          {JOB_REQUIREMENTS.map((requirement, index) => (
            <div
              key={requirement.name}
              style={{ '--lp-delay': `${580 + index * 120}ms` } as React.CSSProperties}
              className="lp-rise flex items-center justify-between gap-3 border-b border-[#F0F3F8] py-4 last:border-b-0"
            >
              <span
                className={`flex items-center gap-3 text-[18px] font-bold ${
                  requirement.met ? 'text-brand-ink' : 'text-brand-faint'
                }`}
              >
                <i
                  className={`grid h-[26px] w-[26px] place-items-center rounded-full text-[14px] font-extrabold ${
                    requirement.met
                      ? 'bg-tone-accent-bg text-brand-600'
                      : 'bg-[#F1F4F9] text-brand-faint'
                  }`}
                >
                  {requirement.met ? '✓' : '·'}
                </i>
                {requirement.name}
              </span>
              <span
                className={`text-[13.5px] font-bold ${
                  requirement.met ? 'text-brand-muted' : 'text-brand-faint'
                }`}
              >
                {requirement.note}
              </span>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between gap-4 bg-[#F6F8FC] px-7 pt-5 pb-6">
          <div className="flex flex-1 flex-col gap-2">
            <span className="text-[13px] font-extrabold tracking-[0.06em] text-brand-muted">
              필수 기술요건 일치 <b className="text-brand-ink">3 / 4</b>
            </span>
            <div className="flex gap-1.5">
              {[true, true, true, false].map((filled, index) => (
                <i
                  key={index}
                  className={`h-2 flex-1 rounded ${filled ? 'bg-brand-600' : 'bg-[#D6DDE7]'}`}
                />
              ))}
            </div>
          </div>
          <CountUp
            value={75}
            run
            suffix="%"
            className="text-[40px] leading-none font-extrabold tracking-[-0.04em] text-brand-600"
          />
        </div>
      </Rise>
    </div>
  )
}

export function WhatIfScene() {
  return (
    <div className="mx-auto flex w-[min(1120px,88vw)] flex-col items-center gap-[clamp(32px,5vh,56px)] text-center text-brand-ink">
      <Rise className="flex flex-col items-center gap-4">
        <h2 className="text-[clamp(38px,3.8vw,60px)] leading-[1.14] font-extrabold tracking-[-0.04em] break-keep [text-wrap:balance]">
          그렇다면,
          <br />
          다음에는 무엇을 배우면 좋을까?
        </h2>
      </Rise>

      <div className="grid w-full items-center gap-[clamp(16px,3vw,56px)] max-lg:gap-8 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
        <Rise delay={260} className="flex flex-col items-center gap-1.5 lg:items-end lg:text-right">
          <span className="text-[14px] font-extrabold tracking-[0.14em] text-brand-muted">현재</span>
          <CountUp
            value={12}
            run
            className="block text-[clamp(72px,10vw,160px)] leading-[.95] font-extrabold tracking-[-0.06em]"
          />
          <span className="text-[16px] font-semibold text-brand-muted">
            필수 기술요건 완전 일치 공고
          </span>
        </Rise>

        <div className="flex min-w-[240px] flex-col items-center gap-4">
          <span
            style={{ '--lp-delay': '520ms' } as React.CSSProperties}
            className="lp-rise inline-flex items-center gap-2.5 rounded-full border border-[#D6DDE7] bg-white px-5 py-3 text-[17px] font-extrabold whitespace-nowrap shadow-[0_10px_28px_rgba(25,47,81,.08)]"
          >
            Kafka <span className="font-bold text-brand-faint">L1</span>
            <Arrow className="h-[18px] w-[18px] text-brand-600" />
            <span className="text-brand-600">L2</span>
          </span>
          {/* 선이 좌우로 그어지며 두 숫자를 잇는다. 여기가 이 장의 인과다. */}
          <div
            aria-hidden
            style={{ '--lp-delay': '700ms' } as React.CSSProperties}
            className="lp-draw h-[3px] w-full rounded-sm bg-[linear-gradient(90deg,rgba(47,94,235,0),#2F5EEB,rgba(47,94,235,0))]"
          />
          <Rise delay={980}>
            <CountUp
              value={15}
              run
              prefix="+"
              className="block text-[clamp(56px,7vw,112px)] leading-none font-extrabold tracking-[-0.05em] text-brand-600"
            />
            <span className="mt-1 block text-[15px] font-bold text-[#465873]">
              새로 요건이 일치하는 공고
            </span>
          </Rise>
        </div>

        <Rise delay={1140} className="flex flex-col items-center gap-1.5 lg:items-start lg:text-left">
          <span className="text-[14px] font-extrabold tracking-[0.14em] text-brand-600">
            L2 확보 시
          </span>
          <CountUp
            value={27}
            run
            className="block text-[clamp(72px,10vw,160px)] leading-[.95] font-extrabold tracking-[-0.06em]"
          />
          <span className="text-[16px] font-semibold text-brand-muted">
            전체 백엔드 공고 87건 기준
          </span>
        </Rise>
      </div>

      <p className="text-[clamp(16px,1.15vw,19px)] leading-[1.65] break-keep text-[#465873]">
        Kafka Evidence를 L2까지 확보하면 필수 기술요건이 일치하는 공고가{' '}
        <b className="text-brand-600">15개</b> 늘어납니다.
      </p>
    </div>
  )
}

const JOURNEY = ['GITHUB', 'EVIDENCE', 'JOB MATCH', 'NEXT SKILL'] as const

export function StartScene() {
  const start = useStartPath()

  return (
    <div className="mx-auto flex w-[min(900px,88vw)] flex-col items-center gap-11 text-center text-white">
      <Rise className="flex flex-wrap items-center justify-center gap-3.5 text-[13px] font-extrabold tracking-[0.14em] text-white/60">
        {JOURNEY.map((step, index) => (
          <span key={step} className="flex items-center gap-3.5">
            <span className={index === JOURNEY.length - 1 ? 'text-[#91BDFF]' : undefined}>
              {step}
            </span>
            {index < JOURNEY.length - 1 && <i className="h-px w-[22px] bg-white/35" />}
          </span>
        ))}
      </Rise>

      <Rise delay={200}>
        <h2 className="text-[clamp(44px,4.8vw,76px)] leading-[1.12] font-extrabold tracking-[-0.045em] break-keep [text-wrap:balance]">
        이제,
        <br />내 GitHub에서 시작하세요.
        </h2>
      </Rise>

      <Rise delay={420} className="flex flex-col items-center gap-4.5">
        <Link
          to={start}
          className="inline-flex items-center gap-3 rounded-[16px] bg-[linear-gradient(135deg,#2F5EEB,#5B8DFF)] px-9 py-5 text-[19px] font-bold text-white shadow-[0_18px_40px_rgba(47,94,235,.4)]"
        >
          <GithubMark className="h-6 w-6" />내 GitHub 분석 시작하기
        </Link>
        <span className="text-[14px] text-white/60">
          읽기 전용 · 선택한 저장소만 분석 · 코드 원문은 저장하지 않습니다
        </span>
      </Rise>
    </div>
  )
}

function Stat({ value, label, accent = false }: { value: number; label: string; accent?: boolean }) {
  return (
    <span className="flex flex-col gap-1">
      <CountUp
        value={value}
        run
        className={`text-[clamp(40px,3.4vw,54px)] leading-none font-extrabold tracking-[-0.04em] ${
          accent ? 'text-brand-600' : ''
        }`}
      />
      <span className="text-[14px] font-bold text-brand-muted">{label}</span>
    </span>
  )
}

function FileTag({ children, active = false }: { children: string; active?: boolean }) {
  return (
    <span
      className={`rounded-lg border px-2.5 py-1 font-sans text-[12px] font-extrabold tracking-[0.1em] ${
        active
          ? 'border-[#3F73FF] bg-[#2F5EEB] text-white'
          : 'border-white/20 bg-transparent text-white/60'
      }`}
    >
      {children}
    </span>
  )
}

function GithubMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
      <path d="M9 18c-4.51 2-5-2-7-2" />
    </svg>
  )
}

function Arrow({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  )
}
