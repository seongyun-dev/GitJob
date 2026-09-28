import assert from 'node:assert/strict'
import test from 'node:test'

import {
  accountName,
  analysisSettingsRows,
} from '../src/features/mypage/model/analysisSettings.ts'

test('이름이 있으면 그대로 쓴다', () => {
  assert.equal(accountName('octocat'), 'octocat')
  assert.equal(accountName('정민아'), '정민아')
})

/*
  BE 는 프로필 이름이 없으면 GitHub 핸들로 접어서 준다(`MeResponse` 주석). 그래도 공백만
  남는 경우까지 막아 둔다 — 이름 자리가 비면 카드가 아바타만 떠 있는 모양이 된다.
  `UserMenu` 와 같은 규칙이다.
*/
test('이름이 비면 사용자로 접는다', () => {
  assert.equal(accountName(''), '사용자')
  assert.equal(accountName('   '), '사용자')
})

test('목표 직무가 있으면 그 이름을 보여준다', () => {
  const rows = analysisSettingsRows({ targetRoleLabel: '백엔드', analyzedRepositoryCount: null })

  assert.equal(rows.targetRole, '백엔드')
})

test('목표 직무가 없으면 아직 선택하지 않았다고 말한다', () => {
  const rows = analysisSettingsRows({ targetRoleLabel: null, analyzedRepositoryCount: null })

  assert.equal(rows.targetRole, '아직 선택하지 않음')
})

/*
  값의 출처는 `GET /me/technologies` 의 `summary.repositoryCount` 다. BE 가
  `count(DISTINCT l.repository_id) FROM latest` 로 세는 값이라 **저장소별 최신 완료 분석**
  기준이지 지금 고른 목록이 아니다(`TechnologyProfileStore.summary`).

  그래서 문구가 "분석한"이어야 한다. "선택됨"으로 적으면 선택을 바꾸고 아직 분석하지
  않은 사람에게 화면이 틀린 말을 한다 — 현재 선택 개수를 주는 조회는 아직 없다.
*/
test('분석한 저장소 수를 분석 기준으로 말한다', () => {
  assert.equal(
    analysisSettingsRows({ targetRoleLabel: null, analyzedRepositoryCount: 3 }).repository,
    '분석한 저장소 3개',
  )
  assert.equal(
    analysisSettingsRows({ targetRoleLabel: null, analyzedRepositoryCount: 1 }).repository,
    '분석한 저장소 1개',
  )
})

test('선택 상태로 오해할 문구를 쓰지 않는다', () => {
  const text = analysisSettingsRows({
    targetRoleLabel: '백엔드',
    analyzedRepositoryCount: 3,
  }).repository

  for (const forbidden of ['선택됨', '현재 선택', '연결된 저장소', '분석 대상 저장소']) {
    assert.equal(text.includes(forbidden), false, forbidden)
  }
})

/*
  0 과 `null` 을 같은 문구로 접는다. 둘 다 "아직 분석 결과가 없다"는 같은 사실이고,
  조회 실패와 분석 이력 없음을 화면에서 구분할 이유가 없다.
*/
test('분석 이력이 없으면 개수를 말하지 않는다', () => {
  for (const count of [0, null]) {
    assert.equal(
      analysisSettingsRows({ targetRoleLabel: null, analyzedRepositoryCount: count }).repository,
      '분석 이력 없음',
      `count ${count}`,
    )
  }
})

test('두 행은 서로 영향을 주지 않는다', () => {
  const rows = analysisSettingsRows({ targetRoleLabel: '프론트엔드', analyzedRepositoryCount: 2 })

  assert.deepEqual(rows, { repository: '분석한 저장소 2개', targetRole: '프론트엔드' })
})
