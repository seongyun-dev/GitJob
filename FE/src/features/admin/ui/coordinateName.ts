/**
 * 좌표에서 사람이 읽을 짧은 이름을 뽑는다.
 *
 * 목록에서 `org.springframework.kafka:spring-kafka` 전체를 주인공으로 두면 그룹 경로가
 * 시선을 다 먹는다. 판단에 필요한 것은 아티팩트 이름(`spring-kafka`)이고, 전체 좌표는
 * 그 아래 근거로 남긴다.
 *
 * **기술명을 단정하지 않는다.** `spring-kafka`를 "Kafka"로 바꾸지 않는 이유는, 좌표
 * 하나가 곧 기술이 아니라는 판단이 이 화면의 존재 이유이기 때문이다(페이지 주석 참고).
 * 최종 이름은 관리자가 승격 폼에서 직접 정한다.
 *
 * 생태계마다 이름의 경계가 다르다.
 *   MAVEN  group:artifact  → artifact          (그룹은 배포 주체지 기술명이 아니다)
 *   NPM    @scope/name     → 그대로            (스코프까지가 패키지 이름이다)
 *   PYPI   name            → 그대로
 *   NUGET  A.B.C           → 그대로            (점 구분이 곧 패키지 이름이다)
 */
export function coordinateName(ecosystem: string, coordinate: string): string {
  if (ecosystem === 'MAVEN') {
    const artifact = coordinate.split(':')[1]
    return artifact !== undefined && artifact !== '' ? artifact : coordinate
  }
  return coordinate
}

/**
 * 짧은 이름이 좌표와 같으면 전체 좌표를 따로 보여줄 필요가 없다.
 * 같은 문자열을 두 줄로 반복하면 행만 길어진다.
 */
export function hasSeparateCoordinate(ecosystem: string, coordinate: string): boolean {
  return coordinateName(ecosystem, coordinate) !== coordinate
}
