/**
 * 랜딩 서비스 소개 섹션의 내용 · 티켓 S15P21E102-212.
 *
 * **문구를 새로 만들지 않았다.** 전부 제품이 이미 화면에서 쓰고 있는 문장이거나
 * 그 축약이다. 랜딩은 마케팅 지면이라 없는 기능을 약속하기 쉬운 자리인데, 이 제품은
 * "하지 않는 것"이 성격을 이루므로 화면과 다른 말을 하면 첫인상부터 어긋난다.
 *
 * 출처
 *   - `EvidenceOverviewPage` 각주 — Evidence는 점수가 아니라 근거 · Personal/Repository
 *   - `JobMatchPage` 각주 — 기술요건 충족도만, 합격 가능성·취업 확률 계산 안 함
 *   - `RecommendationPage` 각주 — 공고 수 증가분으로만 정렬, 추천 점수 없음
 *   - `EvidenceDetailPage` 각주 — Raw Code Viewer 없음, Permalink로만 연결
 *   - `TechnologyDetailPage` 각주 — Level은 숙련도 점수가 아니라 근거의 누적 상태
 *
 * 숫자는 하나도 넣지 않는다. 로그인 전 화면이라 조회할 사용자가 없고, 연출용 수치는
 * Hero의 미리보기 패널 한 곳으로 이미 제한해 두었다(`landingPreviewData`).
 */

/** 서비스 흐름 3단계. 각 단계의 목적지는 실제 라우트다. */
export const INTRO_STEPS = [
  {
    step: '01',
    title: 'GitHub 저장소를 읽습니다',
    body: '선택한 저장소의 파일 · 설정 · Commit에서 기술을 실제로 썼다는 근거를 찾습니다. 원본 코드는 저장하지 않고 GitHub Permalink로만 연결합니다.',
    to: '/onboarding/repositories',
    linkLabel: '분석할 저장소 고르기',
  },
  {
    step: '02',
    title: '채용공고와 대조합니다',
    body: '목표 직무의 공고가 요구하는 기술을 내 Evidence와 기술 단위로 맞춰 봅니다. 무엇이 충족됐고 무엇이 부족한지 공고마다 나란히 보여줍니다.',
    to: '/jobs',
    linkLabel: '공고 매칭 보기',
  },
  {
    step: '03',
    title: '다음에 배울 것을 알려줍니다',
    body: '어떤 기술을 채우면 기술요건이 맞는 공고가 얼마나 늘어나는지로만 순서를 정합니다. 추천 점수는 만들지 않습니다.',
    to: '/recommendations',
    linkLabel: '다음 기술 보기',
  },
] as const

/** Evidence 설명. 두 축과 네 단계가 이 제품의 판정 언어다. */
export const EVIDENCE_AXES = [
  {
    name: 'Personal',
    body: '본인 Commit으로 확인된 범위입니다. 저장소에 구현이 있어도 내 기여가 확인되지 않으면 여기 오르지 않습니다.',
  },
  {
    name: 'Repository',
    body: '저장소 전체 기준입니다. 팀이 그 기술을 어떻게 쓰는지를 보여주며 Personal과 합쳐 하나의 숫자로 만들지 않습니다.',
  },
] as const

/** Level 사다리. 의미 설명은 등급 정책(S15P21E102-127) 확정 전이라 이름만 쓴다. */
export const EVIDENCE_LADDER = ['L0', 'L1', 'L2', 'L3'] as const
