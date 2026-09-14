import { Link, useParams } from 'react-router'
import type { EvidenceLevelGroup } from '@/features/evidence/api/technologiesApi'
import {
  profileErrorMessage,
  useTechnologyEvidence,
} from '@/features/evidence/hooks/useTechnologyProfile'
import { DataRegion, PageFootnote } from '@/shared/ui/DataRegion'
import { EvidenceLevel } from '@/shared/ui/EvidenceLevel'
import { EvidenceRow } from '@/shared/ui/EvidenceRow'
import { PageHero } from '@/shared/ui/PageHero'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 상세 · 티켓 S15P21E102-212 (확정 디자인 `Final v2`의 `09 Evidence Detail`).
 *
 * v2 구조: 목록 복귀 링크 → hero → Level 2칸(Personal / Repository) →
 * `956/372` split(근거 표 | 다음 Level 안내) → 각주.
 *
 * 근거 표는 v2의 다섯 열을 그대로 쓴다.
 *   유형 / 파일 · 위치 / LEVEL 기여 / 기여자 / GitHub 이동  (52 · 436 · 150 · 130 · 70)
 *
 * v2는 표를 두 그룹으로 나눈다. `Personal Level에 반영된 Evidence`와
 * `Repository Level에만 반영된 Evidence`(타인 Commit → Personal 미반영)다.
 * 이 구분이 이 화면의 핵심이라 그룹 자리를 남기되, 몇 건인지는 API가 준다.
 *
 * 특정 기술의 판정 기준(예: Producer 구현 여부)은 기술마다 달라 하드코딩하지 않는다.
 * `techId`는 실제 route state지만 그것만으로 기술명을 만들 수 없어 제목에 쓰지 않는다.
 *
 * 이 화면의 기능 ownership은 S15P21E102-138(이윤서)에 있다. 시각 적용까지만 한다.
 */
const PROOF_COLUMNS = ['유형', '파일 · 위치', 'LEVEL 기여', '기여자', ''] as const
const PROOF_TEMPLATE = '52px minmax(0,436fr) 150px 130px 70px'

export function EvidenceDetailPage() {
  const { techId } = useParams()
  const evidence = useTechnologyEvidence(techId)
  const levels = evidence.data?.levels ?? []

  return (
    <div>
      <Link
        to="/evidence"
        className="inline-block text-[13px] font-semibold text-brand-muted hover:text-brand-ink"
      >
        ← 내 기술 목록
      </Link>

      <div className="mt-3">
        <PageHero
          eyebrow="EVIDENCE DETAIL"
          title="이 기술의 판정 근거"
          description="어떤 파일과 Commit으로 판정했는지, 어떤 근거가 Personal Level에 반영됐는지 보여줍니다. 코드 원문은 저장하지 않고 GitHub Permalink로만 연결합니다."
        />
      </div>

      {/* v2는 두 Level을 먼저 나란히 대비시킨다. 값은 판정 결과라 비운다. */}
      <div className="mt-6 grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:max-w-[640px]">
        {[
          { label: 'PERSONAL', caption: '본인 Commit 기준' },
          { label: 'REPOSITORY', caption: '저장소 전체 기준' },
        ].map((item) => (
          <div
            key={item.label}
            className="rounded-[14px] border border-brand-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(25,47,81,0.07)]"
          >
            <p className="text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint">
              {item.label}
            </p>
            <p className="mt-2 text-[15px] font-[750] text-brand-faint">판정 후 표시</p>
            <p className="mt-1 text-[12.5px] text-brand-faint">{item.caption}</p>
          </div>
        ))}
      </div>

      <div className="gj-split mt-4">
        <div className="overflow-hidden rounded-[18px] border border-brand-line bg-white shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
          <div
            className="hidden gap-4 border-b border-brand-line px-[22px] py-3 text-[10.5px] font-extrabold tracking-[0.12em] text-brand-faint lg:grid"
            style={{ gridTemplateColumns: PROOF_TEMPLATE }}
          >
            {PROOF_COLUMNS.map((label, index) => (
              <span key={label === '' ? `col-${index}` : label} className="truncate">
                {label}
              </span>
            ))}
          </div>
          <div className="p-4">
            <LevelGroups
              loading={evidence.isPending}
              error={evidence.isError ? profileErrorMessage(evidence.error) : null}
              levels={levels}
            />
          </div>
        </div>

        {/* 오른쪽 열이 둘로 늘어 `gj-split`의 한 칸 안에서 다시 쌓는다. */}
        <div className="grid gap-4">
          <DataRegion
            eyebrow="NEXT LEVEL"
            title="다음 Level 판정 기준"
            hint="어떤 근거가 더 확인되면 Level이 올라가는지 표시됩니다."
          >
            <StateCard
              kind="PREPARING"
              title="판정 기준 준비 중"
              description="기준은 기술마다 달라 등급 정책과 조회 API가 준비된 뒤 표시합니다. 화면에서 만들어내지 않습니다."
            />
          </DataRegion>

          {/*
            v2가 근거 표 옆에 두는 `Kafka 추천 기술 상세 →`. 기술명은 조회 API가
            주는 값이라 붙이지 않는다. `techId`는 실제 route param이라 그대로 넘긴다.
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
              추천 기술 상세 →
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

/**
 * Level 로 묶은 근거.
 *
 * <p>평평하게 나열하면 Spring Security 하나가 82 행이 되고, 같은 파일의 연속된
 * import 세 줄이 세 행을 차지한다. 그 화면은 "왜 L2 인가"에 답하지 않는다.
 * Level → 파일 → 라인 순으로 좁혀 들어가야 사람이 답을 얻는다. 접는 일은 BE 가
 * 한다 -- Level 마다 따로 상한을 걸어야 낮은 Level 이 통째로 사라지지 않는다.</p>
 */
function LevelGroups({
  loading,
  error,
  levels,
}: {
  loading: boolean
  error: string | null
  levels: EvidenceLevelGroup[]
}) {
  if (loading) {
    return <StateCard kind="LOADING" title="불러오는 중" description="판정 근거를 읽고 있습니다." />
  }
  if (error !== null) {
    return <StateCard kind="ERROR" title="근거를 불러오지 못했어요" description={error} />
  }
  if (levels.length === 0) {
    return (
      <StateCard
        kind="INSUFFICIENT_DATA"
        title="이 기술의 근거가 아직 없어요"
        description="Registry에는 있는 기술이지만 분석한 저장소에서 확인되지 않았습니다."
      />
    )
  }

  return (
    <div className="grid gap-5">
      {levels.map((group) => (
        <section key={group.level}>
          <header className="flex flex-wrap items-baseline gap-2">
            <EvidenceLevel level={group.level} />
            <span className="text-[12.5px] text-brand-faint">{group.rules.join(' · ')}</span>
            <span className="ml-auto text-[12px] text-brand-faint">
              근거 {group.evidenceCount.toLocaleString('ko-KR')}건 · 파일 {group.files.length}개
            </span>
          </header>

          <ul className="mt-2 grid gap-1.5">
            {group.files.map((file) => {
              const firstLine = file.lines.at(0)
              return (
                <li key={`${file.repository}:${file.filePath}`}>
                  {/*
                    permalink 가 없으면 EvidenceRow 가 null 을 반환한다. V13 이전
                    분석은 저장소 이름을 안 남겨 링크를 만들 수 없다. 그때는 경로만
                    보여준다 -- 근거가 없는 것과 링크가 없는 것은 다르다.
                  */}
                  {file.permalink === null || firstLine === undefined ? (
                    <span className="font-evidence text-xs text-brand-faint">{file.filePath}</span>
                  ) : (
                    <EvidenceRow
                      repo={file.repository ?? ''}
                      filePath={file.filePath}
                      lineStart={firstLine.startLine}
                      permalink={file.permalink}
                    />
                  )}
                  <span className="ml-1 text-[11px] text-brand-faint">
                    {file.lines.map((line) => `${line.factType} L${line.startLine}`).join(' · ')}
                  </span>
                </li>
              )
            })}
          </ul>

          {group.truncated && (
            <p className="mt-1.5 text-[11px] text-tone-caution">
              근거가 많아 상위 {group.shownCount}건만 표시합니다. 판정에는 전부 반영되어
              있습니다.
            </p>
          )}
        </section>
      ))}
    </div>
  )
}
