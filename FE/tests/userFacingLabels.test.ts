import assert from 'node:assert/strict'
import test from 'node:test'

import {
  TECHNOLOGY_DISPLAY_NAMES,
  stateKindDisplayName,
  technologyDisplayName,
} from '../src/shared/presentation/userFacingLabels.ts'

test('all 44 active Registry technologies have a user-facing name', () => {
  assert.equal(Object.keys(TECHNOLOGY_DISPLAY_NAMES).length, 44)
})

test('registry ids never replace official technology names', () => {
  assert.equal(technologyDisplayName('csharp'), 'C#')
  assert.equal(technologyDisplayName('dotnet'), '.NET')
  assert.equal(technologyDisplayName('spring-framework'), 'Spring Framework')
  assert.equal(technologyDisplayName('mysql'), 'MySQL')
  assert.equal(technologyDisplayName('csharp', 'csharp'), 'C#')
  assert.equal(technologyDisplayName('dotnet', 'dotnet'), '.NET')
  assert.equal(technologyDisplayName('unknown-internal-id'), '알 수 없는 기술')
})

test('internal state enums are presented in Korean', () => {
  assert.equal(stateKindDisplayName('PREPARING'), '준비 중')
  assert.equal(stateKindDisplayName('NO_DATA'), '데이터 없음')
  assert.equal(stateKindDisplayName('NOT_SUPPORTED'), '제공하지 않음')
  assert.equal(stateKindDisplayName('ERROR'), '다시 확인 필요')
})
