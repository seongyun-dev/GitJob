import type { TechnologyEvidence } from '@/features/evidence/api/types'

/**
 * `GET /me/technologies/{techId}/evidence` 응답 fixture · 화면 09 Evidence Detail.
 *
 * 계약은 `features/evidence/api/types.ts`(티켓 208)이고 fixture도 그대로 만족한다.
 * `parseEvidence.ts`를 통과하도록 만들었으므로, 나중에 mock 서버를 붙일 때 이 객체를
 * 그대로 응답 봉투에 실어도 된다.
 *
 * 값은 확정 디자인의 아트보드 09다. 이 화면이 보여주려는 것이 "Repository L2인데
 * Personal L1인 이유"이므로 근거 세 줄의 `scopeType`이 서로 달라야 의미가 있다.
 *   - `build.gradle` 의존성 선언 → PERSONAL · L0
 *   - `KafkaConfig.java:24` 설정 → PERSONAL · L1
 *   - `OrderEventConsumer.java:41` 구현 → REPOSITORY · L2 (타인 Commit)
 *
 * `factType`은 화면의 `DEP` / `CFG` / `IMPL` 배지와 다른 축이다. 배지는 근거의
 * 성격이고 `factType`은 추출기가 무엇을 찾았는지다. 계약이 허용하는 5종에서만 골랐다.
 *
 * **`IMPORT`·`DEPENDENCY` 외의 값이 섞여 있는 것은 의도다.** 지금 추출기가 있는 것은
 * 둘뿐이지만(`IMPLEMENTED_FACT_TYPES`), 화면은 `CONFIG_KEY`·`ANNOTATION`이 왔을 때도
 * 무너지지 않아야 한다. 추출기가 늘 때 디자인을 다시 하지 않으려고 미리 넣었다.
 */
export const KAFKA_EVIDENCE: TechnologyEvidence = {
  techId: 'kafka',
  techName: 'Apache Kafka',
  repoLevel: 'L2',
  personalLevel: 'L1',
  criteria: {
    analysisId: 'anl-20260911-0142',
    registryVersion: 'registry-20260908.1',
  },
  evidences: [
    {
      evidenceId: 90211,
      scopeType: 'PERSONAL',
      level: 'L0',
      matchedRule: 'L0-a',
      factType: 'DEPENDENCY',
      repoFullName: 'dev-user/GitJob',
      filePath: 'build.gradle',
      // 매니페스트 스캔에서 나온 근거라 줄 번호가 없다. 0이 아니라 null인 것이 계약이다.
      lineNo: null,
      commitSha: '3f9a2c1d84b7e0526a1c9f3d70b8e4152c6a9d38',
      permalink:
        'https://github.com/dev-user/GitJob/blob/3f9a2c1d84b7e0526a1c9f3d70b8e4152c6a9d38/build.gradle',
      inherited: false,
      detectedAt: '2026-07-14T05:22:00Z',
      excludedReason: null,
    },
    {
      evidenceId: 90212,
      scopeType: 'PERSONAL',
      level: 'L1',
      matchedRule: 'L1-b',
      factType: 'CONFIG_KEY',
      repoFullName: 'dev-user/GitJob',
      filePath: 'src/main/java/com/gitjob/config/KafkaConfig.java',
      lineNo: 24,
      commitSha: 'a81d0e7c93f52b6478d1a0c85e39b7f24d6c0a15',
      permalink:
        'https://github.com/dev-user/GitJob/blob/a81d0e7c93f52b6478d1a0c85e39b7f24d6c0a15/src/main/java/com/gitjob/config/KafkaConfig.java#L24',
      inherited: false,
      detectedAt: '2026-07-21T09:40:00Z',
      excludedReason: null,
    },
    {
      // 이 화면의 요점. 구현 근거는 있는데 타인 Commit이라 Personal에 반영되지 않는다.
      evidenceId: 90213,
      scopeType: 'REPOSITORY',
      level: 'L2',
      matchedRule: 'L2-c',
      factType: 'ANNOTATION',
      repoFullName: 'dev-user/RO-KI',
      filePath: 'src/main/java/com/roki/order/OrderEventConsumer.java',
      lineNo: 41,
      commitSha: 'c04b77e21f5a8d6390be4c17d25f80a9e3b61c47',
      permalink:
        'https://github.com/dev-user/RO-KI/blob/c04b77e21f5a8d6390be4c17d25f80a9e3b61c47/src/main/java/com/roki/order/OrderEventConsumer.java#L41',
      inherited: false,
      detectedAt: '2026-08-02T06:11:00Z',
      excludedReason: null,
    },
  ],
  unmetRules: [
    {
      rule: 'L2-b',
      description: 'Producer 또는 Consumer 구현이 본인 Commit으로 확인되지 않았습니다.',
    },
  ],
  nextActions: [
    {
      fromLevel: 'L1',
      targetLevel: 'L2',
      ruleId: 'L2-b',
      message:
        'KafkaTemplate 전송 또는 @KafkaListener 소비 로직을 본인 Commit으로 Push한 뒤 재분석하세요.',
    },
  ],
  // 0도 의미가 있는 값이라 빠짐없이 채운다. 무엇을 왜 뺐는지 세어 보여주는 자리다.
  excludedCounts: { bot: 2, merge: 5, forkBase: 0, formatOnly: 3, generated: 1 },
}

/**
 * 제외된 근거를 포함한 변형 · `includeExcluded=true` 조회.
 *
 * `excludedReason`이 붙은 항목이 목록에 섞여 올 때 표가 어떻게 보이는지 확인할
 * fixture다. 이 항목들은 버려진 게 아니라 사유와 함께 남는 것이므로 화면도 지우지 않고
 * 이유를 보여줘야 한다.
 */
export const KAFKA_EVIDENCE_WITH_EXCLUDED: TechnologyEvidence = {
  ...KAFKA_EVIDENCE,
  evidences: [
    ...KAFKA_EVIDENCE.evidences,
    {
      evidenceId: 90214,
      scopeType: 'REPOSITORY',
      level: 'L1',
      matchedRule: 'L1-b',
      factType: 'CONFIG_KEY',
      repoFullName: 'dev-user/GitJob',
      filePath: 'docker-compose.yml',
      lineNo: 12,
      commitSha: 'e57a1b93d0c6482f7a35e91d84b0c62f5d7a3e08',
      permalink:
        'https://github.com/dev-user/GitJob/blob/e57a1b93d0c6482f7a35e91d84b0c62f5d7a3e08/docker-compose.yml#L12',
      inherited: false,
      detectedAt: '2026-07-30T02:05:00Z',
      excludedReason: 'BOT_COMMIT',
    },
  ],
}
