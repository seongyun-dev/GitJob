import type { StateKind } from '@/shared/ui/StateCard'

/** Registry 44의 tech_id와 공식 표시 이름. 계산과 URL은 id를 유지하고 화면에만 사용한다. */
export const TECHNOLOGY_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  c: 'C',
  cpp: 'C++',
  csharp: 'C#',
  go: 'Go',
  java: 'Java',
  kotlin: 'Kotlin',
  python: 'Python',
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  php: 'PHP',
  sql: 'SQL',
  html: 'HTML',
  css: 'CSS',
  'spring-framework': 'Spring Framework',
  'spring-boot': 'Spring Boot',
  jpa: 'JPA',
  mybatis: 'MyBatis',
  dotnet: '.NET',
  nodejs: 'Node.js',
  nestjs: 'NestJS',
  django: 'Django',
  fastapi: 'FastAPI',
  react: 'React',
  nextjs: 'Next.js',
  vuejs: 'Vue.js',
  unity: 'Unity',
  numpy: 'NumPy',
  pandas: 'pandas',
  'scikit-learn': 'scikit-learn',
  pytorch: 'PyTorch',
  tensorflow: 'TensorFlow',
  'apache-spark': 'Apache Spark',
  hadoop: 'Apache Hadoop',
  'apache-kafka': 'Apache Kafka',
  mysql: 'MySQL',
  postgresql: 'PostgreSQL',
  mongodb: 'MongoDB',
  redis: 'Redis',
  docker: 'Docker',
  kubernetes: 'Kubernetes',
  aws: 'AWS',
  azure: 'Azure',
  gcp: 'Google Cloud',
  jenkins: 'Jenkins',
}

export function technologyDisplayName(techId: string, suppliedName?: string | null): string {
  const supplied = suppliedName?.trim()
  return TECHNOLOGY_DISPLAY_NAMES[techId] ?? supplied ?? '알 수 없는 기술'
}

const STATE_KIND_DISPLAY_NAMES: Readonly<Record<StateKind, string>> = {
  LOADING: '불러오는 중',
  EMPTY: '결과 없음',
  ERROR: '다시 확인 필요',
  SUCCESS: '완료',
  PARTIAL: '일부 확인',
  RATE_LIMITED: '잠시 후 다시 시도',
  PREPARING: '준비 중',
  INSUFFICIENT_DATA: '근거 부족',
  NO_DATA: '데이터 없음',
  NOT_SUPPORTED: '제공하지 않음',
}

export function stateKindDisplayName(kind: StateKind): string {
  return STATE_KIND_DISPLAY_NAMES[kind]
}
