import { Link, useParams } from 'react-router'
import type { TechnologyEvidence } from '@/features/evidence/api/types'
import {
  EvidenceProofRows,
  ExcludedCounts,
  PROOF_TABLE_TEMPLATE,
} from '@/features/evidence/components/EvidenceProofRows'
import { DesignMockBadge } from '@/mocks/DesignMockBadge'
import { withDesignFixture } from '@/mocks/designFixtures'
import { ANALYSIS_CONTEXT_REPOS, KAFKA_LEVEL_LADDER } from '@/mocks/fixtures/evidenceScreen'
import { KAFKA_EVIDENCE } from '@/mocks/fixtures/technologyEvidence'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 상세 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `09 Evidence Detail`).
 *
 * v2 구조: 목록 복귀 링크 → hero → Level 2칸(Personal / Repository) →
 * `956/372` split(근거 표 | 다음 Level 안내) → 각주.
 *
 * 조회 API가 없어 값은 디자인 fixture에서 온다(`VITE_DESIGN_FIXTURES=on`).
 * fixture는 Kafka 하나뿐이라 다른 `techId`로 들어오면 값이 없다 — 그 경우를 숨기지
 * 않고 상태 카드로 말한다. 실제 API가 붙으면 `techId`로 조회하게 되므로 이 분기가
 * 그대로 로딩·오류 분기 자리가 된다.
 *
 * 특정 기술의 판정 기준(예: Producer 구현 여부)은 기술마다 달라 하드코딩하지 않는다.
 * fixture의 사다리도 Kafka 전용이며 화면이 만들어내는 값이 아니다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-138(이윤서)에 있다. 시각 적용까지만 한다.
 */
const PROOF_COLUMNS = ['유형', '파일 · 위치', 'LEVEL 기여', '기여자', ''] as const

/** 사다리 단계의 표시. 충족·필요·잠김을 색이 아니라 기호로도 구분한다. */
const LADDER_MARK: Readonly<Record<'DONE' | 'TODO' | 'LOCKED', string>> = {
  DONE: '✓',
  TODO: '△',
  LOCKED: '○',
}

const LADDER_CLASS: Readonly<Record<'DONE' | 'TODO' | 'LOCKED', string>> = {
  DONE: 'text-tone-success',
  TODO: 'text-tone-caution',
  LOCKED: 'text-brand-faint',
}

export function EvidenceDetailPage() {
  const { techId } = useParams()

  /*
   * fixture는 Kafka 하나다. 다른 기술로 들어오면 `null`이고, 그건 오류가 아니라
   * "이 기술의 근거를 아직 못 불러온다"는 상태다.
   */
  const evidence = withDesignFixture<TechnologyEvidence | null>(null, () =>
    techId === undefined || techId === KAFKA_EVIDENCE.techId ? KAFKA_EVIDENCE : null,
  )

  return (
    <div>
      <Link
        to="/evidence"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 내 기술 목록
      </Link>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <PageHero
          eyebrow="EVIDENCE DETAIL"
          title={evidence === null ? '이 기술의 판정 근거' : evidence.techName}
          description="어떤 파일과 Commit으로 판정했는지, 어떤 근거가 Personal Level에 반영됐는지 보여줍니다. 코드 원문은 저장하지 않고 GitHub Permalink로만 연결합니다."
        />
        <DesignMockBadge />
      </div>

      {/* v2는 두 Level을 먼저 나란히 대비시킨다. 이 대비가 화면의 주제다. */}
      <div className="mt-6 grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:max-w-[640px]">
        {[
          { label: 'PERSONAL', caption: '본인 Commit 기준', level: evidence?.personalLevel },
          { label: 'REPOSITORY', caption: '저장소 전체 기준', level: evidence?.repoLevel },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-[14px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
          >
            <p className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
              {item.label}
            </p>
            {item.level === undefined ? (
              <p className="mt-2 text-[15px] font-[750] text-brand-faint">판정 후 표시</p>
            ) : (
              <p className="mt-2 text-[28px] leading-none font-[850] tracking-[-0.04em] text-brand-ink">
                {item.level}
              </p>
            )}
            <p className="mt-1.5 text-[12.5px] text-brand-faint">{item.caption}</p>
          </div>
        ))}
      </div>

      <div className="gj-split mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <div
            className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
            style={{ gridTemplateColumns: PROOF_TABLE_TEMPLATE }}
          >
            {PROOF_COLUMNS.map((label, index) => (
              <span key={label === '' ? `col-${index}` : label} className="truncate">
                {label}
              </span>
            ))}
          </div>
          <div className="p-4">
            {evidence === null ? (
              <StateCard
                kind="PREPARING"
                title="근거를 아직 불러올 수 없어요"
                description="근거를 돌려주는 조회 API가 준비되면 이 표에 채워집니다. Personal Level에 반영된 근거와 저장소에만 있는 근거를 구분해 보여줍니다."
              />
            ) : (
              <EvidenceProofRows evidence={evidence} />
            )}
          </div>
          {/*
            Level 기여 규칙. 표 아래에 두는 이유는 각 행의 `L0`·`L1`·`L2`가 무엇을
            뜻하는지 같은 자리에서 읽혀야 하기 때문이다. v2도 같은 위치에 둔다.
          */}
          <p className="border-t border-brand-line px-[22px] py-3 text-[11.5px] leading-[1.6] text-brand-faint">
            Level 기여 · DEP 선언 = L0 · CFG 설정/사용 = L1 · IMPL 구현 = L2 · 반복 구현 + 다수
            Commit = L3 · Raw Code Viewer 없음 · Permalink만
          </p>
        </div>

        {/* 오른쪽 열이 셋으로 늘어 `gj-split`의 한 칸 안에서 다시 쌓는다. */}
        <div className="grid gap-4">
          <DataRegion
            eyebrow="NEXT LEVEL"
            title={
              evidence === null
                ? '다음 Level 판정 기준'
                : `${evidence.nextActions[0]?.targetLevel ?? 'L2'}가 되려면?`
            }
            hint={
              evidence === null
                ? '어떤 근거가 더 확인되면 Level이 올라가는지 표시됩니다.'
                : evidence.unmetRules[0]?.description
            }
          >
            {evidence === null ? (
              <StateCard
                kind="PREPARING"
                title="판정 기준 준비 중"
                description="기준은 기술마다 달라 등급 정책과 조회 API가 준비된 뒤 표시합니다. 화면에서 만들어내지 않습니다."
              />
            ) : (
              <>
                <ol className="grid gap-1.5">
                  {KAFKA_LEVEL_LADDER.map((step) => (
                    <li
                      key={step.level}
                      className="flex items-center gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                    >
                      <LevelBadge level={step.level} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[12.5px] font-[750] text-brand-ink">
                          {step.title}
                        </p>
                        <p className="mt-0.5 truncate text-[11.5px] text-brand-faint">
                          {step.detail}
                        </p>
                      </div>
                      <span
                        className={`shrink-0 text-[13px] font-black ${LADDER_CLASS[step.state]}`}
                      >
                        {LADDER_MARK[step.state]}
                      </span>
                    </li>
                  ))}
                </ol>
                {/*
                  다음 행동. 진단으로만 끝나지 않게 하려고 계약이 `nextActions`를 두므로
                  화면도 그 문장을 그대로 남긴다.
                */}
                {evidence.nextActions.map((action) => (
                  <p
                    key={action.ruleId}
                    className="mt-3 text-[12.5px] leading-[1.65] text-brand-muted"
                  >
                    {action.message}
                  </p>
                ))}
              </>
            )}
          </DataRegion>

          {evidence !== null && (
            <DataRegion
              eyebrow="EXCLUDED"
              title="노이즈로 제외된 근거"
              hint="버리지 않고 사유별로 세어 둡니다. 0건도 사실이므로 함께 표시합니다."
            >
              <ExcludedCounts counts={evidence.excludedCounts} />
            </DataRegion>
          )}

          <DataRegion
            eyebrow="REPOSITORY CONTEXT"
            title="어느 저장소의 근거인가"
            hint="저장소마다 본인 Commit 비중이 달라 Personal Level에 반영되는 범위가 다릅니다."
          >
            {evidence === null ? (
              <StateCard
                kind="NO_DATA"
                title="아직 분석한 저장소가 없어요"
                description="이 기술의 근거가 어느 저장소에서 나왔는지 표시됩니다."
              />
            ) : (
              <ul className="grid gap-2">
                {ANALYSIS_CONTEXT_REPOS.filter((repo) =>
                  evidence.evidences.some((item) => item.repoFullName.endsWith(`/${repo.name}`)),
                ).map((repo) => (
                  <li
                    key={repo.name}
                    className="flex items-center justify-between gap-3 rounded-[12px] border border-brand-line bg-white/70 px-3.5 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[12.5px] font-[750] text-brand-ink">
                        {repo.name}
                      </p>
                      <p className="mt-0.5 truncate text-[11.5px] text-brand-faint">
                        {repo.languages}
                      </p>
                    </div>
                    <span className="shrink-0 text-[11.5px] font-semibold text-brand-muted">
                      {repo.ownCommitText}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </DataRegion>

          {/*
            v2가 근거 표 옆에 두는 `Kafka 추천 기술 상세 →`. 기술명은 조회 결과에서만
            나오므로 없으면 일반 문구로 둔다.
          */}
          <DataRegion
            eyebrow="NEXT SKILL"
            title="추천 기술 상세"
            hint="이 기술을 다음 Level로 올리는 학습 안내로 이동합니다."
          >
            <Link
              to={techId === undefined ? '/recommendations' : `/technologies/${techId}`}
              className="block rounded-xl border border-brand-line bg-white px-5 py-3 text-center text-[13.5px] font-[750] text-brand-ink hover:border-brand-line-active"
            >
              {evidence === null ? '추천 기술 상세 →' : `${evidence.techName} 추천 기술 상세 →`}
            </Link>
          </DataRegion>
        </div>
      </div>

      <PageFootnote>
        Raw Code Viewer는 제공하지 않습니다. 각 근거는 GitHub Permalink로 원문을 확인합니다.
        {techId !== undefined && (
          <>
            {' · '}
            기술 <span className="font-evidence text-brand-muted">{techId}</span>
          </>
        )}
      </PageFootnote>
    </div>
  )
}
