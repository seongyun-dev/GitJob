import type {
  AnswerSource,
  PainTopic,
  PainTopicList,
  ProjectTemplate,
  ProjectTemplateList,
  ProjectTemplateStep,
  TechnologyFaq,
  TechnologyFaqList,
} from '@/features/technology/api/types'
import { get } from '@/shared/api/client'
import { readers } from '@/shared/api/parse'
import { DATA_STATUSES } from '@/shared/types/domain'

/**
 * 학습 지원 HTTP 계층 · 티켓 S15P21E102-281.
 *
 * 이 파일만 경로 문자열을 안다. 세 엔드포인트 모두 BE에 아직 없다(명세 상태 `시작 전`).
 *
 * `techId`는 라우트 파라미터에서 오므로 인코딩한다 — 주소창에서 고칠 수 있고 `../`나
 * `?`가 섞이면 다른 엔드포인트를 부르게 된다.
 */

const r = readers('technology')

function parseSources(source: Record<string, unknown>, at: string): AnswerSource[] {
  return r.array(source, 'sources', at).map((item, index) => {
    const itemAt = `${at}.sources[${index}]`
    const entry = r.item(item, itemAt)
    return {
      label: r.string(entry, 'label', itemAt),
      url: r.string(entry, 'url', itemAt),
    }
  })
}

function parseStep(value: unknown, at: string): ProjectTemplateStep {
  const source = r.item(value, at)
  return {
    order: r.number(source, 'order', at),
    title: r.string(source, 'title', at),
    description: r.string(source, 'description', at),
    evidenceHint: r.string(source, 'evidenceHint', at),
  }
}

function parseTemplate(value: unknown, at: string): ProjectTemplate {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    title: r.string(source, 'title', at),
    summary: r.string(source, 'summary', at),
    difficultyText: r.string(source, 'difficultyText', at),
    steps: r.array(source, 'steps', at).map((item, i) => parseStep(item, `${at}.steps[${i}]`)),
    reviewedAt: r.string(source, 'reviewedAt', at),
  }
}

function parseFaq(value: unknown, at: string): TechnologyFaq {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    question: r.string(source, 'question', at),
    answer: r.string(source, 'answer', at),
    sources: parseSources(source, at),
    reviewedAt: r.string(source, 'reviewedAt', at),
  }
}

function parsePainTopic(value: unknown, at: string): PainTopic {
  const source = r.item(value, at)
  return {
    id: r.string(source, 'id', at),
    title: r.string(source, 'title', at),
    summary: r.string(source, 'summary', at),
    frequencyText: r.string(source, 'frequencyText', at),
    sources: parseSources(source, at),
  }
}

/** 세 응답이 `techId`·`dataStatus`·`items`·`note`로 같은 모양이라 껍데기를 공유한다. */
function parseList<T>(value: unknown, at: string, parseItem: (item: unknown, at: string) => T) {
  const source = r.root(value, at)
  return {
    techId: r.string(source, 'techId', at),
    dataStatus: r.enum(source, 'dataStatus', at, DATA_STATUSES),
    items: r.array(source, 'items', at).map((item, i) => parseItem(item, `${at}.items[${i}]`)),
    note: r.string(source, 'note', at),
  }
}

function path(techId: string, resource: string): string {
  return `/technologies/${encodeURIComponent(techId)}/${resource}`
}

/** 프로젝트 가이드 · 명세 B-FN-019 (화면 11 `무엇을 만들어 볼까` 탭). */
export async function fetchProjectTemplates(techId: string): Promise<ProjectTemplateList> {
  const body = await get<unknown>(path(techId, 'project-templates'))
  return parseList(body, 'projectTemplates', parseTemplate)
}

/** 기술 FAQ · 명세 B-FN-022 (화면 11 `자주 막히는 지점` 탭). */
export async function fetchTechnologyFaqs(techId: string): Promise<TechnologyFaqList> {
  const body = await get<unknown>(path(techId, 'faqs'))
  return parseList(body, 'technologyFaqs', parseFaq)
}

/** 기술 Pain Topic · 명세 F-PAI-01. */
export async function fetchPainTopics(techId: string): Promise<PainTopicList> {
  const body = await get<unknown>(path(techId, 'pain-topics'))
  return parseList(body, 'painTopics', parsePainTopic)
}
