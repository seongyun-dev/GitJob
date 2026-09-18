import type {
  AnalysisContextRepository,
  ReinforcementItem,
} from '@/features/evidence/model/overview'
import { LevelBadge } from '@/shared/ui/LevelBadge'
import { StateCard } from '@/shared/ui/StateCard'

/**
 * Evidence 화면 우측 패널 2종 · 티켓 S15P21E102-204.
 *
 * 확정 디자인 `Final v2`의 `08 My Evidence`는 372px 패널에 두 블록을 쌓는다.
 *   근거 보강 필요  — 저장소엔 있지만 내 Commit에는 없는 기술
 *   ANALYSIS CONTEXT — 어떤 저장소를 분석했는지와 본인 Commit 비중
 *
 * 두 블록 모두 값은 조회 API가 준다. 값이 없을 때의 상태 카드를 지우지 않고 남긴
 * 이유는 그게 현재 develop의 실제 모습이기 때문이다 — 디자인 fixture를 끄면
 * 그대로 돌아온다(`src/mocks/README.md`).
 */

/**
 * Personal Level이 Repository Level보다 낮은 기술이 모이는 자리.
 *
 * 이 구분이 이 제품의 핵심이다. "저장소에 구현은 있는데 내 Commit 근거가 없다"는
 * 것은 기술이 없다는 뜻이 아니라 **판정 범위가 다르다**는 뜻이라, 부족한 기술과
 * 섞어 보여주면 사용자가 자기 상태를 잘못 읽는다.
 */
export function ReinforcementPanel({ items }: { items?: readonly ReinforcementItem[] }) {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
            근거 보강 필요
          </p>
          <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
            저장소에는 있지만 내 코드에서는 확인되지 않은 기술
          </h2>
        </div>
        {items !== undefined && (
          <span className="shrink-0 rounded-full bg-tone-caution-bg px-2.5 py-1 text-[11px] font-extrabold text-tone-caution">
            {items.length}
          </span>
        )}
      </div>

      <div className="mt-4">
        {items === undefined ? (
          <StateCard
            kind="PREPARING"
            title="아직 판정 결과가 없어요"
            description="저장소 수준보다 내 수준이 낮은 기술이 여기에 표시됩니다."
          />
        ) : items.length === 0 ? (
          <StateCard
            kind="EMPTY"
            title="보강이 필요한 기술이 없어요"
            description="저장소 수준보다 내 수준이 낮은 기술이 없습니다."
          />
        ) : (
          <ul className="grid gap-2">
            {items.map((item) => (
              <li
                key={item.techId}
                className="flex items-center gap-3 rounded-[14px] border border-brand-line bg-white/70 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-[750] text-brand-ink">{item.techName}</p>
                  <p className="mt-0.5 truncate text-[11.5px] leading-[1.5] text-brand-muted">
                    {item.reason}
                  </p>
                </div>
                {/*
                  두 Level을 화살표로 잇는다. "지금 여기, 저장소는 저기"가 한 눈에
                  보여야 이 패널의 뜻이 전달된다.
                */}
                <div className="flex shrink-0 items-end gap-1.5">
                  <div className="grid justify-items-center gap-1">
                    <span className="text-[10.5px] text-brand-faint">내 코드</span>
                    <LevelBadge level={item.personalLevel} />
                  </div>
                  <span aria-hidden className="text-[11px] text-brand-faint">
                    →
                  </span>
                  <div className="grid justify-items-center gap-1">
                    <span className="text-[10.5px] text-brand-faint">저장소</span>
                    <LevelBadge level={item.repoLevel} variant="repository" />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

/**
 * 분석 맥락. 어떤 저장소를 근거로 판정했는지 밝힌다.
 *
 * Level만 보여주고 근거 범위를 감추면 "왜 이 Level인가"에 답할 수 없다.
 */
export function AnalysisContextPanel({
  repositories,
  footer,
}: {
  repositories?: readonly AnalysisContextRepository[]
  /** 분석 시각 · 상태 · Snapshot 기준 한 줄. */
  footer?: string
}) {
  return (
    <section className="rounded-[18px] border border-brand-line bg-white p-[22px] shadow-[0_10px_28px_rgba(25,47,81,0.07)]">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-brand-600">
        분석 기준
      </p>
      <h2 className="mt-1.5 text-[17px] leading-[1.3] font-[750] tracking-[-0.03em] text-brand-ink">
        무엇을 근거로 판정했나
      </h2>

      <div className="mt-4">
        {repositories === undefined ? (
          <StateCard
            kind="NO_DATA"
            title="아직 분석한 저장소가 없어요"
            description="저장소를 분석하면 사용 근거가 여기에 표시됩니다."
          />
        ) : repositories.length === 0 ? (
          <StateCard
            kind="NO_DATA"
            title="아직 분석한 저장소가 없어요"
            description="저장소 분석이 완료되면 기준 커밋과 근거 수가 표시됩니다."
          />
        ) : (
          <ul className="grid gap-2">
            {repositories.map((repo) => (
              <li
                key={repo.repositoryId}
                className="rounded-[14px] border border-brand-line bg-white/70 px-4 py-3"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <p className="truncate text-[13px] font-[750] text-brand-ink">{repo.name}</p>
                  <p className="shrink-0 text-[11.5px] text-brand-faint">
                    근거 {repo.evidenceCount.toLocaleString('ko-KR')}건
                  </p>
                </div>
                <details className="mt-2 text-[12px] text-brand-muted">
                  <summary className="w-fit cursor-pointer font-semibold text-brand-muted hover:text-brand-ink">
                    분석 정보 보기
                  </summary>
                  <p className="mt-1.5 break-all font-evidence text-[11.5px] text-brand-faint">
                    기준 버전 {repo.commitSha.slice(0, 7)} ·{' '}
                    {new Date(repo.analyzedAt).toLocaleString('ko-KR')}
                  </p>
                </details>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="mt-4 text-[12.5px] leading-[1.6] text-brand-faint">
        {footer ?? '저장소별 최신 성공 분석을 기준으로 표시합니다.'}
      </p>
    </section>
  )
}
