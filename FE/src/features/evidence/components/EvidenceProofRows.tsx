import type { EvidenceItem, TechnologyEvidence } from '@/features/evidence/api/types'
import { CodePath, EvidenceKind } from '@/shared/ui/CodePath'
import { LevelBadge } from '@/shared/ui/LevelBadge'

/**
 * 근거 표의 본문 · 화면 09 Evidence Detail.
 *
 * 확정 디자인 `Final v2`는 표를 두 그룹으로 나눈다.
 *   Personal Level에 반영된 Evidence
 *   Repository Level에만 반영된 Evidence (타인 Commit → Personal 미반영)
 *
 * **이 구분이 화면의 전부다.** 근거를 한 목록으로 합치면 "저장소에 구현이 있는데
 * 내 Level은 왜 낮은가"에 답할 수 없다. 그래서 `scopeType`으로 나눈다.
 *
 * 열은 v2의 다섯 개이고 폭도 그 값이다(52 · 436 · 150 · 130 · 70).
 *
 * 원문 코드는 렌더하지 않는다. 계약에 필드가 없고(명세가 "원본 코드는 응답에 포함하지
 * 않는다"고 못 박는다) 화면도 Raw Code Viewer를 제공하지 않는다. `permalink`가 원문
 * 확인의 유일한 경로다.
 */
export const PROOF_TABLE_TEMPLATE = '52px minmax(0,436fr) 150px 130px 70px'

/**
 * `factType`을 v2의 배지 문자로 바꾼다.
 *
 * 배지(`DEP`·`CFG`·`IMPL`)는 근거의 성격이고 `factType`은 추출기가 무엇을 찾았는지라
 * 서로 다른 축이다. 표에 두 축을 함께 놓을 자리가 없어 배지 쪽을 택했고, 매핑을
 * 여기 한 곳에 둔다. 계약의 5종을 모두 덮어 두어 추출기가 늘어도 빈 칸이 나오지 않는다.
 */
const FACT_BADGE: Readonly<Record<EvidenceItem['factType'], string>> = {
  DEPENDENCY: 'DEP',
  IMPORT: 'IMP',
  CONFIG_KEY: 'CFG',
  ANNOTATION: 'IMPL',
  API_CALL: 'IMPL',
}

/** 파일 경로 표시. 줄 번호가 없는 근거(매니페스트 스캔)는 경로만 보여준다. */
function formatLocation(item: EvidenceItem): string {
  return item.lineNo === null ? item.filePath : `${item.filePath}:${item.lineNo}`
}

/** Commit 표기. 앞 7자만 쓰는 것은 GitHub 관례이고 v2도 그렇게 적는다. */
function formatCommit(item: EvidenceItem): string {
  return `commit ${item.commitSha.slice(0, 7)} · ${item.detectedAt.slice(0, 10)}`
}

function ProofRow({ item, contributorText }: { item: EvidenceItem; contributorText: string }) {
  return (
    <div
      className="grid items-start gap-4 rounded-[12px] px-[10px] py-3 max-lg:grid-cols-1"
      style={{ gridTemplateColumns: PROOF_TABLE_TEMPLATE }}
    >
      <EvidenceKind>{FACT_BADGE[item.factType]}</EvidenceKind>

      <div className="min-w-0">
        <CodePath>{formatLocation(item)}</CodePath>
        <p className="mt-1.5 text-[12px] text-brand-muted">
          {item.repoFullName}
          {item.excludedReason !== null && (
            <>
              {' · '}
              <span className="font-semibold text-tone-caution">
                제외 · {item.excludedReason}
              </span>
            </>
          )}
        </p>
        <p className="mt-0.5 font-evidence text-[11.5px] text-brand-faint">{formatCommit(item)}</p>
      </div>

      <div className="flex items-center gap-2">
        <LevelBadge level={item.level} />
        <span className="text-[11.5px] text-brand-faint">기여</span>
      </div>

      <p className="text-[12.5px] font-semibold text-brand-muted">{contributorText}</p>

      {/*
        원문 확인 링크. `permalink`가 유일한 경로라 이 열을 비워 두지 않는다.
        새 탭으로 여는 이유는 표에서 자리를 잃지 않게 하려는 것이다.
      */}
      <a
        href={item.permalink}
        target="_blank"
        rel="noreferrer"
        className="text-[12.5px] font-semibold text-brand-600 hover:underline"
      >
        GitHub ↗
      </a>
    </div>
  )
}

export function EvidenceProofRows({ evidence }: { evidence: TechnologyEvidence }) {
  const personal = evidence.evidences.filter((item) => item.scopeType === 'PERSONAL')
  const repositoryOnly = evidence.evidences.filter((item) => item.scopeType === 'REPOSITORY')

  return (
    <div className="grid gap-1">
      <section>
        <div className="flex flex-wrap items-center gap-2.5 px-[10px] pt-2 pb-2">
          <p className="text-[12px] font-extrabold tracking-[0.04em] text-brand-ink-soft">
            Personal Level에 반영된 Evidence
          </p>
          <span className="rounded-full bg-tone-accent-bg px-2.5 py-1 text-[11px] font-extrabold text-tone-accent">
            {personal.length}
          </span>
        </div>
        <div className="divide-y divide-[#F1F4F9]">
          {personal.map((item) => (
            <ProofRow key={item.evidenceId} item={item} contributorText="본인 Commit" />
          ))}
        </div>
      </section>

      {repositoryOnly.length > 0 && (
        <section className="mt-3 border-t border-brand-line pt-2">
          <div className="flex flex-wrap items-center gap-2.5 px-[10px] pt-2 pb-2">
            <p className="text-[12px] font-extrabold tracking-[0.04em] text-brand-ink-soft">
              Repository Level에만 반영된 Evidence
            </p>
            <span className="rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[11px] font-extrabold text-tone-neutral">
              {repositoryOnly.length}
            </span>
            <p className="min-w-0 flex-1 truncate text-[11.5px] text-brand-faint">
              타인 Commit → Personal 미반영
            </p>
          </div>
          <div className="divide-y divide-[#F1F4F9]">
            {repositoryOnly.map((item) => (
              <ProofRow key={item.evidenceId} item={item} contributorText="타인 Commit" />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/**
 * 노이즈로 제외된 건수 · 계약의 `excludedCounts`.
 *
 * 0도 의미가 있는 값이라 0인 항목을 숨기지 않는다. "무엇을 왜 뺐는지"를 세어
 * 보여주는 자리이므로, 0이면 "그 사유로 뺀 것이 없다"는 사실을 말한다.
 */
export function ExcludedCounts({ counts }: { counts: TechnologyEvidence['excludedCounts'] }) {
  const items = [
    { label: '봇 Commit', value: counts.bot },
    { label: 'Merge', value: counts.merge },
    { label: 'Fork base', value: counts.forkBase },
    { label: '형식만 변경', value: counts.formatOnly },
    { label: '생성 코드', value: counts.generated },
  ]

  return (
    <ul className="grid grid-cols-2 gap-2">
      {items.map((item) => (
        <li
          key={item.label}
          className="flex items-baseline justify-between gap-2 rounded-[10px] border border-brand-line bg-white/70 px-3 py-2"
        >
          <span className="truncate text-[12px] text-brand-muted">{item.label}</span>
          <span className="shrink-0 text-[13px] font-[750] tabular-nums text-brand-ink-soft">
            {item.value}
          </span>
        </li>
      ))}
    </ul>
  )
}
