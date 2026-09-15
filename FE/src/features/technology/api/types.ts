import type { DataStatus } from '@/shared/types/domain'

/**
 * 학습 지원 조회 응답 타입 · 티켓 S15P21E102-281.
 *
 * BE 미구현 상태에서 먼저 고정하는 계약이다. 근거는 B조 API 명세서 v0.1.
 *
 *   - B-FN-019 프로젝트 가이드 조회 `GET /technologies/{techId}/project-templates`
 *   - B-FN-022 기술 FAQ 목록 조회   `GET /technologies/{techId}/faqs`
 *   - F-PAI-01 기술 Pain Topic 조회 `GET /technologies/{techId}/pain-topics`
 *
 * ## 확정 범위가 이 계열에서 무엇을 뺐는가
 *
 * 명세 확정 범위가 두 가지를 못 박았고, 타입이 그것을 반영한다.
 *
 * **프로젝트 가이드는 검수된 정적 자료다.** AI 자유 생성·완료 추적·자동 Level 부여를
 * 제공하지 않는다. 그래서 진행률·완료 플래그 필드가 없다. 두면 다음 사람이 체크박스를
 * 만들고, 그 체크가 아무 데도 저장되지 않는다는 것은 나중에야 드러난다.
 *
 * **FAQ는 사전 생성 후 사람이 검수한 목록이다.** 자유 질문 챗봇이 아니다. 그래서
 * 질문을 보내는 타입이 없고 `answer`가 이미 채워져 온다.
 *
 * **출처·인용이 필수다.** 근거가 부족하면 답을 만들지 않고 `ANSWER_NOT_SUPPORTED`로
 * 미공개 처리한다 — 그래서 `sources`가 optional이 아니고, 답이 없는 항목은 애초에
 * 목록에 오지 않는다.
 *
 * ## 화면 11의 `왜 필요한가`·`Level 기준` 탭은 여기 없다
 *
 * 두 탭에 대응하는 엔드포인트가 명세 v0.1에 **없다.** 추천 근거는
 * `GET /me/recommendations`의 `reasons`가 주고(매칭 계열), Level 기준은 Registry
 * 규칙에서 나오는 값인데 그것을 기술 단위로 돌려주는 조회가 아직 없다. 계약을
 * 지어내지 않고 fixture로 남겨 둔다 — 계약 문서 미결에 올렸다.
 */

/** 프로젝트 가이드의 한 단계. */
export interface ProjectTemplateStep {
  /** 단계 순서. 서버가 정한다 — 배열 순서와 별개로 표시할 번호다. */
  order: number
  title: string
  description: string
  /** 이 단계를 마치면 어떤 근거가 남는지. 학습 안내의 핵심 문구다. */
  evidenceHint: string
}

/**
 * 검수된 프로젝트 가이드 한 건.
 *
 * `reviewedAt`이 있는 이유는 이 자료가 **사람이 검수한 것**이라는 사실이 화면에
 * 보여야 하기 때문이다. AI가 방금 만든 것과 구분되지 않으면 확정 범위가 무의미해진다.
 */
export interface ProjectTemplate {
  id: string
  title: string
  summary: string
  /** 난이도 표기. 서버 문구를 그대로 쓴다. */
  difficultyText: string
  steps: ProjectTemplateStep[]
  reviewedAt: string
}

export interface ProjectTemplateList {
  techId: string
  dataStatus: DataStatus
  items: ProjectTemplate[]
  note: string
}

/** 인용 출처. 답변마다 필수다. */
export interface AnswerSource {
  label: string
  url: string
}

/** 검수된 FAQ 한 건. */
export interface TechnologyFaq {
  id: string
  question: string
  answer: string
  sources: AnswerSource[]
  reviewedAt: string
}

export interface TechnologyFaqList {
  techId: string
  dataStatus: DataStatus
  items: TechnologyFaq[]
  /** `자유 질문 챗봇은 제공하지 않습니다` 같은 범위 안내. */
  note: string
}

/** 자주 막히는 지점 한 건. */
export interface PainTopic {
  id: string
  title: string
  summary: string
  /** 이 주제가 얼마나 자주 나오는지에 대한 서버 표기. 점수가 아니라 문구다. */
  frequencyText: string
  sources: AnswerSource[]
}

export interface PainTopicList {
  techId: string
  dataStatus: DataStatus
  items: PainTopic[]
  note: string
}
