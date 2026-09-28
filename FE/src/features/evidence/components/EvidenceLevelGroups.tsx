import { useState } from 'react'
import type { EvidenceFile, EvidenceLevelGroup } from '@/features/evidence/api/technologiesApi'
import { EvidenceLevel } from '@/shared/ui/EvidenceLevel'

/**
 * 판정 근거 목록 · 화면 09 Evidence Detail · 티켓 S15P21E102-252.
 *
 * ## 무엇이 읽기 어려웠나
 *
 * 이전 화면은 파일마다 `file.lines` 를 그대로 이어 붙였다.
 *
 *     MINAH714/ssaju / frontend/src/pages/GroupCreateDialog.tsx:28
 *     API_CALL L28 · API_CALL L29 · API_CALL L30 · API_CALL L31 · API_CALL L32 ...
 *
 * 한 줄에서 **실제로 다른 정보는 숫자뿐인데** `API_CALL` 이 여덟 번 반복된다. 게다가
 * 저장소 이름(`MINAH714/ssaju`)이 열여섯 행에 그대로 다시 나와, 정작 읽어야 할 파일
 * 경로가 반복되는 글자 사이에 묻혔다. L1 묶음은 파일 16개가 전부 `IMPORT L1` 하나씩이라
 * 화면의 절반이 같은 말이었다.
 *
 * ## 세 가지를 접었다
 *
 *   1. **같은 값은 한 번만.** `factType` 은 파일마다 배지 하나로 올리고, 줄은 번호만
 *      칩으로 늘어놓는다. 한 파일 안에서 종류가 섞이면 그때만 배지를 여럿 보여준다
 *   2. **저장소로 묶는다.** 저장소 이름을 소제목으로 올리고 아래 행에서는 뺀다.
 *      같은 이름이 반복되지 않으면 경로가 눈에 들어온다
 *   3. **낮은 Level 은 접는다.** 판정을 결정한 것은 가장 높은 Level 이고, 그 아래는
 *      "왜 이 Level 인가"를 이미 아는 사람이 확인하러 여는 자리다
 *
 * 접기만 하고 **덜어내지는 않는다.** 근거 수와 파일 수는 접힌 상태에서도 머리에
 * 남아 있고, 펼치면 전부 그대로 있다. 근거가 실제보다 적어 보이는 것은 이 제품에서
 * 표시 오류가 아니라 사실 왜곡이다.
 */

/**
 * `factType` → 배지 문자.
 *
 * `EvidenceProofRows` 가 쓰는 매핑과 같은 값이다. 그쪽은 계약 타입(`api/types.ts`)의
 * 5종 유니온을 키로 받고 이쪽 `technologiesApi` 는 `factType` 이 그냥 `string` 이라
 * 타입이 달라 공유하지 못했다. 두 계약이 하나로 합쳐질 때 함께 정리한다.
 */
const FACT_BADGE: Readonly<Record<string, string>> = {
  DEPENDENCY: '의존성',
  IMPORT: '불러오기',
  CONFIG_KEY: '설정',
  ANNOTATION: '구현',
  API_CALL: '구현',
}

/** 한 파일에서 보여 줄 줄 번호의 최대 개수. 넘으면 나머지는 수로만 알린다. */
const MAX_LINE_CHIPS = 10

/** 접기 전에 보여 줄 파일 수. 저장소 묶음 하나가 화면을 넘기지 않는 선. */
const MAX_FILES_COLLAPSED = 6

function badgeOf(factType: string): string {
  return FACT_BADGE[factType] ?? '사용'
}

/** 파일 경로를 디렉터리와 파일명으로 가른다. 파일명만 진하게 둬야 눈이 거기서 멈춘다. */
function splitPath(filePath: string): { dir: string; name: string } {
  const at = filePath.lastIndexOf('/')
  return at === -1
    ? { dir: '', name: filePath }
    : { dir: filePath.slice(0, at + 1), name: filePath.slice(at + 1) }
}

/** 줄 표기. 한 줄짜리는 번호 하나, 범위면 `28–35`. */
function lineLabel(line: { startLine: number; endLine: number }): string {
  return line.endLine > line.startLine ? `${line.startLine}–${line.endLine}` : `${line.startLine}`
}

function FileRow({ file }: { file: EvidenceFile }) {
  const { dir, name } = splitPath(file.filePath)

  // 파일 안에서 실제로 나온 종류만 배지로 올린다. 대개 하나다.
  const kinds = [...new Set(file.lines.map((line) => badgeOf(line.factType)))]
  const shown = file.lines.slice(0, MAX_LINE_CHIPS)
  const rest = file.lines.length - shown.length

  return (
    <li className="grid gap-1.5 rounded-[10px] px-2.5 py-2.5 hover:bg-tone-neutral-bg/60">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {kinds.map((kind) => (
          <span
            key={kind}
            className="shrink-0 rounded-md bg-tone-accent-bg px-1.5 py-0.5 font-evidence text-[10px] font-extrabold tracking-[0.04em] text-tone-accent"
          >
            {kind}
          </span>
        ))}

        {/*
          경로는 한 덩어리로 둔다. 디렉터리를 흐리게 두면 줄바꿈이 일어나도 파일명이
          어디인지 바로 보인다. 좁은 화면에서 잘리는 쪽은 앞(디렉터리)이어야 한다.
        */}
        <span className="min-w-0 font-evidence text-[12.5px] break-all">
          <span className="text-brand-faint">{dir}</span>
          <span className="font-semibold text-brand-ink">{name}</span>
        </span>

        {file.permalink !== null && (
          <a
            href={file.permalink}
            target="_blank"
            rel="noreferrer"
            className="ml-auto shrink-0 text-[11.5px] font-semibold text-brand-600 hover:underline"
          >
            GitHub ↗
          </a>
        )}
      </div>

      {/*
        줄 번호. `API_CALL` 을 줄마다 되풀이하던 자리다 — 종류는 위 배지가 이미
        말했으므로 여기서는 숫자만 남긴다.
      */}
      <div className="flex flex-wrap items-center gap-1">
        {shown.map((line) => (
          <span
            key={`${line.startLine}-${line.endLine}-${line.ruleId}`}
            className="rounded bg-tone-neutral-bg px-1.5 py-0.5 font-evidence text-[11px] tabular-nums text-brand-muted"
          >
            L{lineLabel(line)}
          </span>
        ))}
        {rest > 0 && <span className="text-[11px] text-brand-faint">외 {rest}줄</span>}
      </div>
    </li>
  )
}

/** 저장소 이름으로 묶는다. 파일 순서는 서버가 준 그대로 둔다 — 정렬은 판정의 일부다. */
function groupByRepository(files: EvidenceFile[]): { repo: string; files: EvidenceFile[] }[] {
  const groups = new Map<string, EvidenceFile[]>()
  for (const file of files) {
    // V12 이전 분석은 저장소 이름을 안 남긴다. 그때는 이름 없는 묶음 하나로 모은다.
    const repo = file.repository ?? ''
    const bucket = groups.get(repo)
    if (bucket === undefined) {
      groups.set(repo, [file])
    } else {
      bucket.push(file)
    }
  }
  return [...groups].map(([repo, list]) => ({ repo, files: list }))
}

function RepositoryBlock({ repo, files }: { repo: string; files: EvidenceFile[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? files : files.slice(0, MAX_FILES_COLLAPSED)
  const rest = files.length - shown.length

  return (
    <div className="rounded-[12px] border border-brand-line bg-white/70">
      <div className="flex flex-wrap items-baseline gap-2 border-b border-brand-line px-3 py-2">
        <span className="min-w-0 truncate font-evidence text-[12px] font-semibold text-brand-ink-soft">
          {repo === '' ? '저장소 이름 없음' : repo}
        </span>
        <span className="text-[11.5px] text-brand-faint">파일 {files.length}개</span>
      </div>

      <ul className="grid gap-0.5 p-1.5">
        {shown.map((file) => (
          <FileRow key={file.filePath} file={file} />
        ))}
      </ul>

      {rest > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full border-t border-brand-line px-3 py-2 text-[12px] font-semibold text-brand-600 hover:bg-tone-accent-bg/40"
        >
          파일 {rest}개 더 보기
        </button>
      )}
    </div>
  )
}

/**
 * Level 묶음 하나.
 *
 * `defaultOpen` 이 첫 묶음에만 참이다. 가장 높은 Level 이 판정을 결정했으므로 그것만
 * 펼쳐 두고, 아래는 접어 둔 채 수만 보여준다.
 */
function LevelSection({ group, defaultOpen }: { group: EvidenceLevelGroup; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const repositories = groupByRepository(group.files)

  return (
    <section className="overflow-hidden rounded-[14px] border border-brand-line bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3 text-left hover:bg-tone-neutral-bg/50"
      >
        <EvidenceLevel level={group.level} />

        <span className="min-w-0 flex-1" />

        <span className="shrink-0 text-[12px] tabular-nums text-brand-faint">
          근거 {group.evidenceCount.toLocaleString('ko-KR')}건 · 파일 {group.files.length}개
        </span>

        <span aria-hidden className="shrink-0 text-[11px] text-brand-faint">
          {open ? '접기 ▲' : '펼치기 ▼'}
        </span>
      </button>

      {open && (
        <div className="grid gap-2 border-t border-brand-line bg-tone-neutral-bg/25 p-2.5">
          {repositories.map((entry) => (
            <RepositoryBlock key={entry.repo} repo={entry.repo} files={entry.files} />
          ))}

          {group.truncated && (
            <p className="px-1 text-[11.5px] text-tone-caution">
              근거가 많아 상위 {group.shownCount}건만 표시합니다. 판정에는 전부 반영되어
              있습니다.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

export function EvidenceLevelGroups({ levels }: { levels: EvidenceLevelGroup[] }) {
  return (
    <div className="grid gap-2.5">
      {levels.map((group, index) => (
        <LevelSection key={group.level} group={group} defaultOpen={index === 0} />
      ))}
    </div>
  )
}
