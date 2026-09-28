# 실제 채용 표본과 Python 언어 매핑을 위한 Registry Snapshot

상태: 로컬 검증 완료. 기준일: 2026-09-08. 관련 Jira: S15P21E102-88, S15P21E102-31.

## 버전과 변경

`AI/registry/data/technology_registry_20260908_1.json`은 기존
`technology-registry/v1` schema의 독립 Snapshot `registry-20260908.1`이다.
과거 `technology_registry_v1.json` 및 그 `registry-20260901.1` 버전을 보존한다.
새 Snapshot은 이전 37개 기술 및 47개 매핑을 모두 동일하게 포함하며,
10개 기술과 11개 매핑만 추가해 47개 기술·58개 매핑을 가진다.

develop의 FE TypeScript 전환 통합 시 두 Snapshot의 React import 로컬 근거 경로를
`FE/src/main.jsx#react`에서 `FE/src/main.tsx#react`로 함께 정정했다.
두 파일에서 같은 React import를 확인했으며 기술 ID·별칭·판정·버전은 변경하지 않았다.
이는 로컬 근거의 경로 정정이므로 JSON 파일 bytes는 이전 제출본과 다르다.
Worker 이미지도 새 경로의 실제 파일을 패키징하며, 과거 계산 결과는 재작성하지 않는다.

9/7 저장된 Worknet 5건/Saramin 5건의 UNKNOWN 24개 언급 중 기술 표현을 검수했다.
아래 추가는 이 표본에 실제 존재한 표현만 대상으로 하며 시장 대표성을 의미하지 않는다.
REST API는 REST 방식의 API 요건을 보존하는 식별자이며 프레임워크로 치환하지 않는다.

| 새 tech_id / EXACT ALIAS | 표시명 | 표본 언급 수 | 공식 근거 |
|---|---|---:|---|
| html | HTML | 4 | [HTML Standard](https://html.spec.whatwg.org/multipage/) |
| css | CSS | 3 | [W3C CSS](https://www.w3.org/Style/CSS/) |
| kotlin | Kotlin | 1 | [Kotlin](https://kotlinlang.org/docs/home.html) |
| aws | AWS | 2 | [AWS 문서](https://docs.aws.amazon.com/index.html) |
| linux | Linux | 3 | [Linux](https://docs.kernel.org/admin-guide/index.html) |
| sql | SQL | 1 | [SQL 언어](https://www.postgresql.org/docs/current/tutorial-sql.html) |
| django | Django | 2 | [Django](https://docs.djangoproject.com/en/5.2/) |
| mysql | MySQL | 2 | [MySQL](https://dev.mysql.com/doc/) |
| rest-api | REST API | 3 | [REST](https://developer.mozilla.org/en-US/docs/Glossary/REST) |
| git | Git | 3 | [Git](https://git-scm.com/docs) |

기존 Python 기술에는 `GITHUB_LANGUAGE`, `EXACT`, `Python` 매핑을 하나 추가했다.
근거는 commit `054c7dbc527518fa2ecfd316efe2aa01f3986c39`에 고정한
[Innovation Graph languages.csv](https://github.com/github/innovationgraph/blob/054c7dbc527518fa2ecfd316efe2aa01f3986c39/data/languages.csv)다.
채용 별칭 추가가 라이브러리나 도구의 GITHUB_LANGUAGE 매핑을 생성하지 않는다.

## 소비와 검증

호출자는 명시적으로 선택한 Snapshot을 기존 `load_registry`/`RegistryMapper`에 넣고
결과에 Registry 버전을 기록한다. 기존 버전으로 산출한 결과는 새 버전으로 재표시하지 않는다.
`tests/test_registry_mvp_snapshot.py`는 기존 엔트리 유지, 정확한 추가 범위,
새 별칭 10개 및 Python 언어 매핑을 검증한다. 기존 Registry 계약/seed/Mapper 테스트와
함께 103개가 통과했다. 이 검증은 실제 원문 AND/OR 조건 확정이나 전체 수요 품질 인수가 아니다.
