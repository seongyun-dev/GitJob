package com.example.git_job.analysis.service;

import org.springframework.stereotype.Component;

/**
 * 분석 요청에 박아 넣을 Registry 버전을 DB에서 읽는다.
 *
 * <p>예전에는 설정값이었고, 기본값이 {@code technology-registry/v1}이었다. 그것은
 * schema_version이지 registry_version이 아니다. 실재하지 않는 버전으로 규칙을
 * 조회하면 0행이 나오고, 0행은 "매칭된 기술 없음"과 구분되지 않는다. 아직 판정
 * 단계가 없어 증상이 없었을 뿐, 붙이는 순간 조용히 틀린 결과를 낸다.</p>
 *
 * <p>C Registry의 활성 경계는 {@code technology_registry_alias}다. 과거
 * {@code technology_registry.status = CURRENT}는 새 불변 Snapshot 발행 이전의
 * lifecycle이라 두 값을 섞으면 새 분석도 구형 규칙으로 실행된다. 새 요청은
 * {@link TechnologyRegistryVersionResolver}를 통해 활성 alias만 사용한다.</p>
 *
 * <p>캐시하지 않는다. 분석 요청은 사람이 누르는 빈도이고, 조회는 한 행짜리
 * 인덱스 조회다. 캐시를 두면 새 버전을 발행해도 TTL이 지나야 반영되거나 재기동이
 * 필요해지는데, 그 대가를 낼 만큼 잦은 경로가 아니다.</p>
 */
@Component
public class CurrentRegistryVersion {

    private final TechnologyRegistryVersionResolver resolver;

    public CurrentRegistryVersion(TechnologyRegistryVersionResolver resolver) {
        this.resolver = resolver;
    }

    /**
     * @throws com.example.git_job.global.exceptions.CustomException 활성 alias가 없거나
     *         승인된 불변 Snapshot을 가리키지 않을 때. 임의 버전으로 진행하지 않는다.
     */
    public String resolve() {
        return resolver.resolveForNewRequest(
                TechnologyRegistryVersionResolver.SUPPORTED_SCHEMA_VERSION);
    }
}
