/**
 * 실제 API로 연결된 화면이 디자인 fixture를 import하지 못하게 막는다 (S15P21E102-279).
 *
 * 인수 조건이 "운영 빌드에서 withDesignFixture 결과가 표시되지 않을 것"이다. fixture
 * 스위치는 기본이 꺼짐이지만, 그것만으로는 "켜면 가짜 값이 나온다"는 상태가 남는다.
 * 연결이 끝난 화면은 아예 import 경로를 끊어 두는 것이 더 확실하다.
 *
 * 이 검사를 lint 규칙이 아니라 스크립트로 두는 이유는 oxlint 1.80의 `overrides`에서
 * `no-restricted-imports`가 켜지지 않기 때문이다. 조용히 아무것도 검사하지 않는 규칙을
 * 설정 파일에 남겨 두면, 다음 사람은 보호받고 있다고 믿는다.
 *
 * 아직 조회 API가 없는 화면은 목록에서 빠져 있다. 그 화면들은 `DesignMockBadge`를
 * 달고 있고, API가 생기는 순간 여기에 추가한다.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

/** 연결이 끝난 영역. 여기서 fixture를 부르면 실패다. */
const CONNECTED = ['src/features/evidence', 'src/features/matching', 'src/features/trend']

const FIXTURE_IMPORT = /from\s+['"]@\/mocks(?:\/[^'"]*)?['"]/

function walk(dir) {
  const entries = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      entries.push(...walk(path))
    } else if (/\.tsx?$/.test(name)) {
      entries.push(path)
    }
  }
  return entries
}

const offenders = []
for (const root of CONNECTED) {
  for (const file of walk(root)) {
    const source = readFileSync(file, 'utf8')
    source.split('\n').forEach((line, index) => {
      if (FIXTURE_IMPORT.test(line)) {
        offenders.push(`${relative('.', file)}:${index + 1}  ${line.trim()}`)
      }
    })
  }
}

if (offenders.length > 0) {
  console.error('연결된 화면이 디자인 fixture를 import하고 있습니다 (S15P21E102-279):\n')
  offenders.forEach((offender) => console.error(`  ${offender}`))
  console.error('\n화면 타입은 features/*/model/view.ts, 값은 조회 API에서 가져옵니다.')
  process.exit(1)
}

console.log(`fixture 경계 검사 통과 — ${CONNECTED.join(', ')}`)
