import { PageHero } from '@/shared/ui/PageHero'
import {
  PROJECT_CODE,
  TEAM_EMAIL,
  TEAM_FLOW,
  TEAM_GROUPS,
  TEAM_MEMBERS,
  TEAM_NAME,
} from '@/shared/constants/team'

/**
 * 팀 소개 · 하단바에서 들어온다.
 *
 * 명단·조 편성·담당 영역·연락처는 `shared/constants/team`이 갖는다. 이 화면은
 * 배치만 한다.
 *
 * 조를 카드 세 장으로 나란히 두고 그 위에 흐름을 한 줄로 얹었다. 표로 만들면 세
 * 조가 서로 독립된 항목처럼 읽히는데, 실제로는 A조 결과를 C조가 받고 그 결과를
 * B조가 받는 한 줄짜리 구조다. 그 관계가 편성 자체보다 중요하다.
 *
 * 카드는 A·B·C 순(팀 요약 표와 같은 순서), 흐름 줄은 A → C → B 순이다. 둘은 서로
 * 다른 순서이고 그래서 `team.ts`도 배열을 따로 갖는다.
 *
 * 상세 업무 목록(각 조의 내부 분담, 세부 기능)은 옮기지 않았다. 이 화면은 누가
 * 무엇을 맡는지 알리는 곳이지 업무 명세를 붙이는 곳이 아니다.
 *
 * 팀원 사진·GitHub 링크·한 줄 소개는 두지 않았다. 받은 자료가 없고, 자리를 만들어
 * 두면 비어 있는 채로 남거나 누군가 임의로 채우게 된다.
 */

/** 조 카드 하나. 세 장이 같은 골격이라 컴포넌트로 둔다. */
function GroupCard({ group }: { group: (typeof TEAM_GROUPS)[number] }) {
  return (
    <li className="flex flex-col rounded-[18px] border border-brand-line bg-white/70 px-6 py-6">
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-tone-accent-bg px-2.5 py-1 text-[11px] font-extrabold tracking-[0.08em] text-tone-accent">
          {group.id}조
        </span>
        <span className="text-[12px] font-medium text-brand-faint">
          {group.members.length}명
        </span>
      </div>

      <h3 className="mt-3 text-[16px] leading-[1.35] font-[750] tracking-[-0.02em] break-keep text-brand-ink">
        {group.focus}
      </h3>
      <p className="mt-2 text-[13px] leading-[1.75] break-keep text-brand-muted">
        {group.summary}
      </p>

      {/*
        멤버. 조 안에서는 팀장만 배지를 단다 — 나머지에 `팀원` 배지를 달면 배지가
        아무것도 구분하지 못한다.
      */}
      <ul className="mt-5 flex flex-wrap gap-2">
        {group.members.map((member) => (
          <li
            key={member.name}
            className="flex items-center gap-1.5 rounded-[10px] border border-brand-line bg-white px-3 py-2"
          >
            <span className="text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
              {member.name}
            </span>
            {member.lead === true && (
              <span className="text-[10px] font-extrabold tracking-[0.08em] text-tone-accent">
                LEAD
              </span>
            )}
          </li>
        ))}
      </ul>

      {/*
        맡는 일. `mt-auto`로 카드 아래에 붙여, 조마다 설명 길이가 달라도 세 카드의
        이 줄이 같은 높이에서 시작하게 한다.
      */}
      <div className="mt-auto pt-5">
        <p className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
          맡는 일
        </p>
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {group.areas.map((area) => (
            <li
              key={area}
              className="rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[12px] font-medium text-brand-muted"
            >
              {area}
            </li>
          ))}
        </ul>
      </div>
    </li>
  )
}

export function TeamPage() {
  return (
    <div className="flex flex-col gap-10">
      <PageHero
        eyebrow="TEAM"
        title={TEAM_NAME}
        description={`SSAFY 15기 자율 프로젝트 ${PROJECT_CODE} 팀입니다. ${TEAM_MEMBERS.length}명이 세 조로 나뉘어 GitJob을 만들고 있습니다.`}
      />

      <section className="rounded-[18px] border border-brand-line bg-white/70 px-6 py-7 lg:px-8">
        <h2 className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
          WHAT WE BUILD
        </h2>
        <p className="mt-3 max-w-[68ch] text-[14px] leading-[1.8] break-keep text-brand-body">
          GitJob은 GitHub 저장소를 분석해 사용자의 기술 사용 근거를 만들고, 목표 직무의
          채용 수요와 비교해 Skill Gap과 다음 학습 기술을 제안하는 서비스입니다.
        </p>
        <p className="mt-3 max-w-[68ch] text-[14px] leading-[1.8] break-keep text-brand-muted">
          기술 레벨은 숙련도나 채용 가능성의 확률이 아니라, 등록된 규칙에 의해 판정된
          상태입니다. 서로 다른 출처의 지표를 임의의 종합 점수로 합치지 않습니다.
        </p>
      </section>

      <section>
        <h2 className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
          HOW WE WORK
        </h2>

        {/*
          조 사이의 흐름. 세 조가 독립된 항목이 아니라 한 줄로 이어진다는 것을 카드보다
          먼저 보여준다. 화살표는 장식이 아니라 데이터가 가는 방향이다.

          좁은 화면에서는 세로로 쌓이므로 화살표를 90도 돌린다. 가로 화살표가 세로로
          쌓인 항목 사이에 남으면 방향이 틀린 그림이 된다.
        */}
        <ol className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          {TEAM_FLOW.map((step, index) => (
            <li key={step.id} className="flex items-center gap-2 sm:gap-3">
              <span className="rounded-full border border-brand-line bg-white/70 px-4 py-2 text-[13px] font-semibold whitespace-nowrap text-brand-body">
                <span className="text-brand-600">{step.id}조</span> {step.label}
              </span>
              {index < TEAM_FLOW.length - 1 && (
                <span
                  aria-hidden
                  className="rotate-90 text-[13px] text-brand-faint sm:rotate-0"
                >
                  →
                </span>
              )}
            </li>
          ))}
        </ol>

        <ul className="mt-3 grid gap-3 lg:grid-cols-3">
          {TEAM_GROUPS.map((group) => (
            <GroupCard key={group.id} group={group} />
          ))}
        </ul>
      </section>

      <section className="rounded-[18px] border border-brand-line bg-white/70 px-6 py-7 lg:px-8">
        <h2 className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
          CONTACT
        </h2>
        <p className="mt-3 text-[14px] leading-[1.7] text-brand-body">
          서비스 문의와 개인정보 관련 요청을 같은 주소에서 받습니다.
        </p>
        <a
          href={`mailto:${TEAM_EMAIL}`}
          className="mt-2 inline-block text-[15px] font-[750] tracking-[-0.01em] text-brand-600 hover:underline"
        >
          {TEAM_EMAIL}
        </a>
      </section>
    </div>
  )
}
