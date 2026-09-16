import { Link, useParams, useSearchParams } from 'react-router'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { NEXT_SKILLS } from '@/mocks/fixtures/nextSkill'
import {
  CURRENT_STATE,
  FAQ_ITEMS,
  FAQ_NOTE,
  LEVEL_CRITERIA,
  LEVEL_CRITERIA_NOTE,
  PROJECT_GUIDE,
  SUPPORTING_EVIDENCE,
  WHY_NEEDED,
} from '@/mocks/fixtures/technologyDetail'
import type { NextSkillFixture } from '@/mocks/types'
import { CodePath } from '@/shared/ui/CodePath'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { MeterBar } from '@/shared/ui/MeterBar'
import { PageHero } from '@/shared/ui/PageHero'
import { StatStrip } from '@/shared/ui/StatStrip'
import type { StatItem } from '@/shared/ui/StatStrip'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * 추천 기술 상세 · 티켓 S15P21E102-212
 * (확정 디자인 `Final v2`의 `11 Recommended Technology Detail`).
 *
 * v2 구조: hero(+Personal / Target / What-if 3축) → 탭 4개 → `956/372` split →
 * 번호가 붙은 근거 섹션 → 각주.
 *
 * **탭을 만든다.** 이전 초안은 "전환할 데이터가 없어 탭으로 만들지 않는다"고 적었고
 * 그 판단은 그때 맞았다. 지금은 탭마다 내용이 있어(디자인 fixture) 전환이 실제로
 * 동작하므로, 누를 수 있는데 아무 일도 없는 컨트롤이 아니다. fixture가 꺼져 있으면
 * 탭도 그리지 않고 예전처럼 섹션 이름만 세운다.
 *
 * 어느 탭인지는 주소에 실린다(`?tab=project`). 새로고침해도 같은 탭이 열려야 하고
 * 팀에 링크를 공유할 수도 있어야 한다.
 *
 * `Personal L1` · `Target L2` · `31 / 87건` 같은 값은 전부 C조 계산 결과이고 조회
 * API가 develop에 없다. FE가 만들지 않는다.
 */
const TABS = [
  { id: 'why', label: '추천 근거' },
  { id: 'project', label: '프로젝트' },
  { id: 'faq', label: 'FAQ / Pain' },
  { id: 'trend', label: 'Trend' },
] as const

/** v2가 나누는 근거 갈래. 이름은 제품 정의라 값 없이도 보여줄 수 있다. */
const SECTIONS = [
  {
    no: '01',
    title: '현재 상태',
    hint: '지금 확인된 Level과 그 근거 파일, Personal과 Repository가 다른 이유',
  },
  {
    no: '02',
    title: '왜 필요한가',
    hint: '비교 중인 공고에서 얼마나 요구되는지, 선행 기술은 충족했는지',
  },
  {
    no: '03',
    title: '무엇을 만들면 되나',
    hint: '어떤 구현이 있으면 다음 Level 근거가 되는지',
  },
  {
    no: '04',
    title: 'FAQ · 자주 막히는 지점',
    hint: '학습·구현에서 자주 나오는 어려움과 참고 자료',
  },
] as const

function toAxes(skill: NextSkillFixture | undefined): readonly StatItem[] {
  const delta = skill === undefined ? null : skill.projectedFullMatch - skill.currentFullMatch

  return [
    {
      label: 'Personal',
      note: skill?.fromLevel ?? '분석 후 표시',
      caption: '본인 Commit으로 확인된 Level',
    },
    {
      label: 'Target',
      note: skill?.targetLevel ?? '계산 후 표시',
      caption: '다음 판정 단계',
    },
    {
      label: 'What-if',
      note: delta === null ? '계산 후 표시' : `+${delta}`,
      caption: '확보 시 새로 충족되는 공고 수',
    },
  ]
}

export function TechnologyDetailPage() {
  const { techId } = useParams()
  const [params, setParams] = useSearchParams()

  /*
   * 추천 화면과 같은 훅을 쓰던 배선을 뗐다 · 티켓 S15P21E102-281 / -279 병합.
   *
   * -281은 명세 v0.1의 추천 DTO(`NextSkill`)를 전제로 이 화면을 붙였는데, -279가
   * 구현한 `GET /me/recommendations`는 그 모양이 아니다. C 계산 엔진이 후보별
   * 목표 Level·헤드라인·CTA 문구·신규 부합 공고 목록을 만들지 않기 때문이고
   * (계약 §6-3), 그 칸을 화면이 채우면 없는 요구를 만들어 낸다.
   *
   * 그래서 이 화면은 fixture 로 되돌린다. 추천 응답에서 이 화면이 쓸 수 있는 것은
   * 기술 ID·순위·근거 문장·공고 수 변화뿐이라, 무엇을 보여줄지 먼저 정해야 한다.
   * 붙일 자리는 `features/matching/api/adapter.ts`의 `toNextSkills`가 갖고 있다.
   */
  const skill = withDesignFixture<NextSkillFixture | undefined>(
    undefined,
    () => NEXT_SKILLS.find((item) => item.techId === techId),
  )

  /*
   * 탭 네 개는 아직 fixture다.
   *
   * `무엇을 만들어 볼까`·`자주 막히는 지점` 둘은 붙일 곳이 생겼고
   * (`hooks/useTechnologyGuides.ts`의 `useProjectTemplates`·`useTechnologyFaqs`),
   * `왜 필요한가`·`Level 기준` 둘은 대응하는 엔드포인트가 명세 v0.1에 **없다.**
   * 탭 하나만 실제 값으로 바꾸면 같은 화면에서 어느 탭이 사실인지 구분되지 않으므로,
   * 네 탭의 내용 교체는 각 탭의 조회가 모두 준비된 뒤에 한 번에 한다. 이 티켓의 범위는
   * 붙일 자리를 만드는 데까지다.
   */
  const detail = withDesignFixture<boolean>(false, () => skill?.techId === 'kafka')

  const requestedTab = params.get('tab')
  const tab = TABS.find((item) => item.id === requestedTab)?.id ?? 'why'

  return (
    <div>
      <Link
        to="/recommendations"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 다음 학습 기술
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="RECOMMENDED TECHNOLOGY"
          title={skill?.techName ?? '이 기술을 왜 추천했나요'}
          description="어떤 순서로 익히고 무엇을 만들면 Evidence를 남길 수 있는지 안내합니다. 학습 안내는 근거를 남기는 방법을 보여주는 것이지 점수를 올리는 방법이 아닙니다."
        />
        <DesignMockBadge />
      </div>

      <div className="mt-6">
        <StatStrip items={toAxes(skill)} />
      </div>

      {/* 탭. 전환할 내용이 있을 때만 그린다 */}
      {detail && (
        <div className="mt-5 flex flex-wrap gap-1.5">
          {TABS.map((item) => {
            const active = item.id === tab
            return (
              <button
                key={item.id}
                type="button"
                aria-pressed={active}
                onClick={() => setParams({ tab: item.id })}
                className={`rounded-[10px] px-4 py-2.5 text-[13.5px] transition-colors ${
                  active
                    ? 'bg-tone-accent-bg font-[750] text-brand-ink'
                    : 'font-semibold text-brand-faint hover:bg-[#F5F7FA]'
                }`}
              >
                {item.label}
              </button>
            )
          })}
        </div>
      )}

      <div className="gj-split mt-4">
        <div className="grid gap-4">
          {!detail ? (
            // fixture가 없으면 예전처럼 갈래 이름만 세운다. 무엇이 들어올 자리인지는
            // 값이 없어도 보여줄 수 있다.
            SECTIONS.map((section) => (
              <DataRegion
                key={section.no}
                eyebrow={section.no}
                title={section.title}
                hint={section.hint}
              >
                <StateCard
                  kind="PREPARING"
                  title="준비 중"
                  description="추천 근거와 학습 가이드를 돌려주는 조회 API가 준비되면 이 자리에 표시합니다."
                />
              </DataRegion>
            ))
          ) : tab === 'why' ? (
            <>
              <DataRegion
                eyebrow="01"
                title="현재 상태"
                hint={CURRENT_STATE.summary}
              >
                <div className="flex flex-wrap items-center gap-2.5">
                  <LevelBadge level={CURRENT_STATE.personalLevel} />
                  <CodePath>{CURRENT_STATE.evidenceFile}</CodePath>
                  <span className="text-[12px] text-brand-faint">
                    {CURRENT_STATE.evidenceCaption}
                  </span>
                </div>
                <p className="mt-3 text-[12.5px] leading-[1.7] text-brand-muted">
                  {CURRENT_STATE.gapReason}
                </p>
              </DataRegion>

              <DataRegion
                eyebrow="02"
                title="왜 필요한가"
                hint={`백엔드 공고 ${WHY_NEEDED.totalJobCount}건 중 ${WHY_NEEDED.requiredCount}건이 필수로 요구`}
              >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
                    <p className="text-[11.5px] text-brand-faint">필수 요구</p>
                    <p className="mt-1 text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                      {WHY_NEEDED.requiredCount}
                      <span className="text-[12px] font-semibold text-brand-faint">
                        {' / '}
                        {WHY_NEEDED.totalJobCount}건
                      </span>
                    </p>
                    <div className="mt-2">
                      <MeterBar
                        value={WHY_NEEDED.requiredCount}
                        total={WHY_NEEDED.totalJobCount}
                        height={5}
                      />
                    </div>
                    <p className="mt-1.5 text-[11.5px] text-brand-faint">{WHY_NEEDED.rankNote}</p>
                  </div>
                  <div className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
                    <p className="text-[11.5px] text-brand-faint">선행 기술</p>
                    <p className="mt-1 text-[15px] font-[750] text-tone-success">
                      {WHY_NEEDED.prerequisiteMet ? '충족' : '미충족'}
                    </p>
                    <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
                      {WHY_NEEDED.prerequisiteText}
                    </p>
                  </div>
                  <div className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3.5">
                    <p className="text-[11.5px] text-brand-faint">What-if</p>
                    <p className="mt-1 text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-600">
                      +{WHY_NEEDED.whatIfDelta}
                    </p>
                    <p className="mt-1.5 text-[11.5px] leading-[1.5] text-brand-faint">
                      {WHY_NEEDED.whatIfText}
                    </p>
                  </div>
                </div>

                {/*
                  반대 방향 신호를 같은 자리에 적는다. 수요가 높다는 근거만 보여주면
                  화면이 한쪽 근거만 제시하게 된다.
                */}
                <p className="mt-3 rounded-[12px] border border-brand-line bg-tone-caution-bg/40 px-4 py-3 text-[12px] leading-[1.65] text-brand-muted">
                  <span className="font-extrabold text-tone-caution">Counter signal · </span>
                  {WHY_NEEDED.counterSignal}
                </p>
              </DataRegion>

              <DataRegion
                eyebrow="03"
                title="어떤 Evidence가 필요한가"
                hint="L2 판정 기준 — 재분석으로만 갱신"
              >
                <ol className="grid gap-2">
                  {LEVEL_CRITERIA.map((item) => (
                    <li
                      key={item.no}
                      className="flex gap-3 rounded-[12px] border border-brand-line bg-white/70 px-4 py-3"
                    >
                      <span className="grid size-5 shrink-0 place-items-center rounded-full bg-tone-accent-bg text-[10.5px] font-extrabold text-tone-accent">
                        {item.no}
                      </span>
                      <div className="min-w-0">
                        <p className="text-[13px] font-[750] text-brand-ink">{item.title}</p>
                        <p className="mt-0.5 text-[12px] leading-[1.6] text-brand-muted">
                          {item.detail}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
                <p className="mt-3 text-[11.5px] leading-[1.65] text-brand-faint">
                  {LEVEL_CRITERIA_NOTE}
                </p>
              </DataRegion>
            </>
          ) : tab === 'project' ? (
            <DataRegion
              eyebrow="04"
              title={PROJECT_GUIDE.title}
              hint={`${PROJECT_GUIDE.difficulty} · ${PROJECT_GUIDE.duration}`}
            >
              <p className="text-[13px] leading-[1.7] text-brand-muted">{PROJECT_GUIDE.summary}</p>

              <p className="mt-5 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
                TASKS
              </p>
              <ol className="mt-2 grid gap-2">
                {PROJECT_GUIDE.tasks.map((task) => (
                  <li
                    key={task.no}
                    className="flex gap-3 rounded-[12px] border border-brand-line bg-white/70 px-4 py-3"
                  >
                    <span className="text-[11px] font-extrabold tabular-nums text-brand-faint">
                      {task.no}
                    </span>
                    <div className="min-w-0">
                      <p className="text-[13px] font-[750] text-brand-ink">{task.title}</p>
                      <p className="mt-0.5 text-[12px] leading-[1.6] text-brand-muted">
                        {task.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>

              <p className="mt-5 text-[11px] font-extrabold tracking-[0.1em] text-brand-faint">
                EVIDENCE GOAL
              </p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {PROJECT_GUIDE.evidenceGoals.map((goal) => (
                  <li
                    key={goal}
                    className="rounded-full border border-brand-line bg-white px-3 py-1.5 text-[12.5px] font-semibold text-brand-muted"
                  >
                    {goal}
                  </li>
                ))}
              </ul>

              <p className="mt-4 rounded-[12px] border border-brand-line bg-tone-caution-bg/40 px-4 py-3 text-[12px] leading-[1.7] text-brand-muted">
                {PROJECT_GUIDE.warning}
              </p>
            </DataRegion>
          ) : tab === 'faq' ? (
            <DataRegion
              eyebrow="FAQ / PAIN POINT"
              title="자주 막히는 부분"
              hint="정리된 목록만 제공합니다. 자유 질문 챗봇은 제공하지 않습니다."
            >
              <ol className="grid gap-2">
                {FAQ_ITEMS.map((item) => (
                  <li
                    key={item.no}
                    className="rounded-[12px] border border-brand-line bg-white/70 px-4 py-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-[13px] font-[750] text-brand-ink">
                        <span className="mr-2 text-[11px] font-extrabold tabular-nums text-brand-faint">
                          {item.no}
                        </span>
                        {item.topic}
                      </p>
                      <p className="text-[11.5px] text-brand-faint">
                        관련 질문 {item.relatedQuestionCount.toLocaleString('ko-KR')}건
                      </p>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-[1.6] text-brand-muted">
                      Q. {item.question}
                    </p>
                  </li>
                ))}
              </ol>
              {/*
                이 탭의 출처가 Stack Overflow인데 그 출처는 현재 수집 입력에 없다
                (`docs/ai/c-public-trend.md` 10행). 질문 건수가 출처 확보에 달려
                있다는 사실을 화면에 남긴다.
              */}
              <p className="mt-3 text-[11.5px] leading-[1.65] text-brand-faint">
                {FAQ_NOTE} 질문 건수는 Stack Overflow 출처가 확보된 뒤 채워집니다.
              </p>
            </DataRegion>
          ) : (
            <DataRegion
              eyebrow="TREND"
              title="이 기술의 출처별 신호"
              hint="출처마다 단위 · 기간 · 기준이 달라 합산하지 않습니다."
            >
              <StateCard
                kind="NOT_SUPPORTED"
                title="이 탭은 트렌드 화면이 담당합니다"
                description="출처별 추이와 성장 단계는 트렌드 상세에서 봅니다. 같은 값을 두 화면이 각각 계산하면 숫자가 어긋납니다."
                action={
                  <Link
                    to={techId === undefined ? '/trends' : `/trends/${techId}`}
                    className="inline-block rounded-xl border border-brand-line px-4 py-2.5 text-[13px] font-[750] text-brand-ink hover:border-brand-line-active"
                  >
                    이 기술의 트렌드 보기
                  </Link>
                }
              />
            </DataRegion>
          )}

          {/*
            v2가 04 섹션 뒤에 두는 안내와 이동. "Task를 완료해도 Level은 바뀌지
            않는다"는 이 제품의 핵심 규칙이라 추천 근거 값이 없어도 문장을 남긴다.
            재분석 진입은 마이페이지가 가지고 있다.
          */}
          <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
            <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
              AFTER IMPLEMENTATION
            </p>
            <p className="mt-2 text-[13px] leading-[1.7] text-brand-muted">
              Evidence는 자동으로 올라가지 않습니다. 구현을 GitHub에 Push한 뒤 다시 분석해야
              본인 Commit 근거로 판정됩니다.
            </p>
            <Link
              to="/mypage"
              className="mt-4 block rounded-xl border border-brand-line bg-white px-5 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              구현 후 GitHub 다시 분석
            </Link>
          </section>
        </div>

        <div className="grid gap-4">
          <DataRegion
            eyebrow="WHAT-IF"
            title={
              skill === undefined
                ? '확보하면 무엇이 달라지나'
                : `${skill.targetLevel} 확보 가정 시`
            }
            hint="목표 Level을 가정했을 때 새로 충족되는 공고를 봅니다."
          >
            {skill !== undefined && (
              <div className="mb-3 flex items-end gap-3">
                <p className="text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-ink-soft">
                  {skill.currentFullMatch}
                </p>
                <span aria-hidden className="text-[13px] text-brand-faint">
                  →
                </span>
                <p className="text-[22px] leading-none font-[850] tracking-[-0.04em] text-brand-600">
                  {skill.projectedFullMatch}
                </p>
                <p className="text-[13px] font-[850] text-brand-600">
                  +{skill.projectedFullMatch - skill.currentFullMatch}
                </p>
              </div>
            )}
            <Link
              to={techId === undefined ? '/what-if' : `/what-if?tech=${techId}`}
              className="block rounded-xl border border-brand-line bg-white px-5 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              새로 충족되는 공고 보기
            </Link>
          </DataRegion>

          <DataRegion
            eyebrow="TREND"
            title="이 기술의 트렌드"
            hint="출처별 추이는 별도 화면에서 봅니다."
          >
            <Link
              to={techId === undefined ? '/trends' : `/trends/${techId}`}
              className="block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              이 기술의 트렌드 보기
            </Link>
          </DataRegion>

          <DataRegion
            eyebrow="EVIDENCE"
            title="지금 내 근거"
            hint="이 기술로 확인된 파일과 Commit을 확인합니다."
          >
            {detail && (
              <ul className="mb-3 grid gap-2">
                {SUPPORTING_EVIDENCE.map((item) => (
                  <li
                    key={item.filePath}
                    className="flex items-center justify-between gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                  >
                    <CodePath>{item.filePath}</CodePath>
                    <span className="shrink-0 font-evidence text-[11px] font-extrabold text-brand-faint">
                      {item.badge}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <Link
              to={techId === undefined ? '/evidence' : `/evidence/${techId}`}
              className="block rounded-xl border border-brand-line px-4 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              근거 상세 보기
            </Link>
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        Level은 숙련도 점수가 아니라 근거의 누적 상태입니다. 학습 안내는 근거를 남기는 방법을
        보여주는 것이지 점수를 올리는 방법이 아닙니다.
      </PageFootnote>
    </div>
  )
}
