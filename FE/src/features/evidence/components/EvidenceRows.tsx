import { Link } from 'react-router'
import type { TechnologyProfile, TechnologyProfileEntry } from '@/features/evidence/api/types'
import { EVIDENCE_TABLE_TEMPLATE } from '@/features/evidence/components/EvidenceTable'
import { REPRESENTATIVE_EVIDENCE } from '@/mocks/fixtures/evidenceScreen'
import { LEVEL_STEPS } from '@/shared/constants/evidenceLevel'
import { CodePath } from '@/shared/ui/CodePath'
import { LevelBadge, LevelLadder } from '@/shared/ui/LevelBadge'

/**
 * 기술별 판정 표의 본문 · 화면 08 My Evidence.
 *
 * 확정 디자인 `Final v2`는 이 표를 카테고리가 아니라 **Level 구간**으로 묶는다
 * (`L2 이상 · 6개` / `L1 · 5개` / `L0 · 3개`). 응답은 카테고리별로 오므로
 * (`TechnologyProfile.categories`) 여기서 다시 묶는다.
 *
 * 묶는 기준을 Personal Level로 둔 것이 중요하다. Repository Level로 묶으면 "저장소엔
 * 있지만 내 Commit에는 없는" 기술이 상위 구간에 들어가 화면이 내 상태를 부풀린다.
 *
 * 열 폭은 `EvidenceTable`의 `TEMPLATE`과 같은 값을 쓴다. 두 곳이 어긋나면 헤더와
 * 본문이 밀린다 — 그래서 상수를 그 파일에서 가져온다.
 */

/** Level 구간. v2의 그룹 헤더 셋이다. 순서가 표의 순서다. */
const GROUPS = [
  {
    id: 'L2_UP',
    title: 'L2 이상',
    caption: '구현 · 본인 Commit 확인',
    /** Personal Level이 L2 이상인 기술. */
    match: (entry: TechnologyProfileEntry) => LEVEL_STEPS[entry.personalLevel] >= 2,
  },
  {
    id: 'L1',
    title: 'L1',
    caption: '설정 · 사용 확인 — 구현 근거 보강 필요',
    match: (entry: TechnologyProfileEntry) => LEVEL_STEPS[entry.personalLevel] === 1,
  },
  {
    id: 'L0',
    title: 'L0',
    caption: '선언만 확인 — 사용 코드 없음',
    match: (entry: TechnologyProfileEntry) => LEVEL_STEPS[entry.personalLevel] === 0,
  },
] as const

/** 대표 Evidence 문구를 techId로 찾는다. 계약에 없는 값이라 fixture에서만 온다. */
function findRepresentative(techId: string) {
  return REPRESENTATIVE_EVIDENCE.find((item) => item.techId === techId)
}

function TechnologyRow({ entry }: { entry: TechnologyProfileEntry }) {
  const representative = findRepresentative(entry.techId)

  return (
    <Link
      to={`/evidence/${entry.techId}`}
      className="grid items-center gap-[18px] rounded-[12px] px-[10px] py-3 transition-colors hover:bg-[#F7F9FC] max-lg:grid-cols-1"
      style={{ gridTemplateColumns: EVIDENCE_TABLE_TEMPLATE }}
    >
      {/* 기술 · Repository Level이 더 높으면 그 사실을 이름 아래에 붙인다 */}
      <div className="min-w-0">
        <p className="truncate text-[13.5px] font-[750] tracking-[-0.01em] text-brand-ink">
          {entry.techName}
        </p>
        {representative?.gapNote != null && (
          <p className="mt-1 truncate text-[11.5px] text-tone-caution">{representative.gapNote}</p>
        )}
      </div>

      {/* PERSONAL — 배지와 사다리를 함께. 값과 단계를 동시에 읽게 한다 */}
      <div className="flex items-center gap-2.5">
        <LevelBadge level={entry.personalLevel} />
        <LevelLadder level={entry.personalLevel} />
      </div>

      {/* REPOSITORY — 글자만. 같은 값이라도 근거 범위가 달라 시각 무게를 낮춘다 */}
      <div>
        <LevelBadge level={entry.repoLevel} variant="repository" />
      </div>

      {/* 대표 EVIDENCE */}
      <div className="min-w-0">
        {representative === undefined ? (
          <p className="text-[12.5px] text-brand-faint">대표 근거 미확인</p>
        ) : (
          <>
            <CodePath>{representative.filePath}</CodePath>
            <p className="mt-1 truncate text-[11.5px] text-brand-faint">{representative.caption}</p>
          </>
        )}
      </div>

      <span aria-hidden className="text-right text-[15px] text-brand-faint max-lg:hidden">
        →
      </span>
    </Link>
  )
}

export function EvidenceRows({ profile }: { profile: TechnologyProfile }) {
  // 카테고리 경계를 지우고 한 벌로 만든다. v2의 묶음 기준이 Level이기 때문이다.
  const entries = profile.categories.flatMap((category) => category.technologies)

  return (
    <div className="grid gap-1">
      {GROUPS.map((group) => {
        const rows = entries.filter(group.match)
        if (rows.length === 0) {
          // 해당 구간에 기술이 없으면 헤더도 그리지 않는다. 빈 구간 헤더는
          // "여기 뭔가 있어야 하는데 없다"로 읽힌다.
          return null
        }

        return (
          <section key={group.id}>
            <div className="flex flex-wrap items-center gap-2.5 px-[10px] pt-4 pb-2">
              <p className="text-[12px] font-extrabold tracking-[0.06em] text-brand-ink-soft">
                {group.title}
              </p>
              <p className="min-w-0 flex-1 truncate text-[11.5px] text-brand-faint">
                {group.caption}
              </p>
              <span className="shrink-0 rounded-full bg-tone-neutral-bg px-2.5 py-1 text-[11px] font-extrabold text-tone-neutral">
                {rows.length}개
              </span>
            </div>
            <div className="grid gap-0.5 divide-y divide-[#F1F4F9]">
              {rows.map((entry) => (
                <TechnologyRow key={entry.techId} entry={entry} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
