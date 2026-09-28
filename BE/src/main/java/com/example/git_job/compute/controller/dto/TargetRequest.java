package com.example.git_job.compute.controller.dto;

import java.util.List;

/**
 * 목표 직무 저장 요청 (S15P21E102-279).
 *
 * <p>전량 교체다. 필터를 지우는 것도 사용자의 선택이므로 부분 갱신을 두지 않는다 --
 * 두면 "서울만 보기"를 해제할 방법이 없다.</p>
 *
 * <p>직무 문자열이 실제로 지원되는지는 C가 판정한다. 여기서 목록을 복제하면 C가 지원
 * 직무를 늘릴 때마다 두 곳을 고쳐야 하고, 어긋나는 동안 사용자는 되는 직무를 거절당한다.
 * 이 클래스가 막는 것은 형식뿐이다 -- 빈 값과, 저장 칼럼을 넘길 만큼 긴 값.</p>
 *
 * <p>검증을 서비스가 아니라 여기서 하는 이유는 잘못된 값이 도메인으로 들어가지 않게
 * 하려는 것이다. Bean Validation은 이 프로젝트 의존성에 없어 쓰지 않는다.</p>
 */
public record TargetRequest(String targetRole, List<String> regions, List<String> careerLevels) {

    /** 저장 칼럼은 쉼표로 이어 붙인 200자다. 개수와 길이를 여기서 막는다. */
    private static final int MAX_FILTERS = 10;
    private static final int MAX_FILTER_LENGTH = 40;
    private static final int MAX_ROLE_LENGTH = 60;

    public TargetRequest {
        if (targetRole == null || targetRole.isBlank() || targetRole.length() > MAX_ROLE_LENGTH) {
            throw new IllegalArgumentException("targetRole must be non-blank and at most "
                    + MAX_ROLE_LENGTH + " characters");
        }
        regions = validated(regions, "regions");
        careerLevels = validated(careerLevels, "careerLevels");
    }

    private static List<String> validated(List<String> values, String name) {
        if (values == null) {
            return List.of();
        }
        if (values.size() > MAX_FILTERS) {
            throw new IllegalArgumentException(name + " must hold at most " + MAX_FILTERS
                    + " values");
        }
        for (String value : values) {
            if (value != null && value.length() > MAX_FILTER_LENGTH) {
                throw new IllegalArgumentException(name + " values must be at most "
                        + MAX_FILTER_LENGTH + " characters");
            }
        }
        return List.copyOf(values);
    }
}
