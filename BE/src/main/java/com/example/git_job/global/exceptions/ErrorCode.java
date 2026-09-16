package com.example.git_job.global.exceptions;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

/**
 * REST와 STOMP 공통 오류 계약. 새 오류는 문자열로 직접 만들지 말고 여기에
 * 상수를 추가하고 {@code CustomException(ErrorCode)}로 발생시킨다.
 *
 * <p>코드 형식은 {@code {도메인}-{HTTP 상태}-{일련번호}}이며 클라이언트가 이
 * 문자열로 분기하므로 한 번 배포된 코드 값은 변경하지 않는다. 503 계열은
 * 동시 요청 충돌(CONCURRENT_MODIFICATION) 재시도가 모두 소진된 경우로,
 * 사용자 잘못이 아니라 재시도하면 해소될 수 있는 일시 상태를 뜻한다.</p>
 */
@Getter
@RequiredArgsConstructor
public enum ErrorCode {

    ANALYSIS_NOT_FOUND(HttpStatus.NOT_FOUND, "AN-404-1", "분석을 찾을 수 없습니다."),
    ANALYSIS_ACCESS_DENIED(HttpStatus.FORBIDDEN, "AUTH-403-1", "본인 소유의 분석만 조회할 수 있습니다."),
    // Security 필터 단계의 인가 실패. 지금 hasRole 제한은 /api/v1/admin/** → ADMIN 하나뿐이라
    // 이 코드가 뜨는 상황은 곧 "로그인은 됐지만 관리자가 아니다"이다. 재로그인으로는 해소되지
    // 않으므로(권한은 DB에서 부여) 클라이언트는 이 코드를 세션 만료(AUTH-401-*)와 다르게 안내한다.
    ADMIN_ROLE_REQUIRED(HttpStatus.FORBIDDEN, "AUTH-403-2", "관리자 권한이 필요합니다."),

    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "G-500", "서버 내부 오류가 발생했습니다."),
    INVALID_REQUEST_BODY(HttpStatus.BAD_REQUEST, "G-400-1", "요청 본문이 올바르지 않습니다."),
    INVALID_REQUEST_PARAMETER(
            HttpStatus.BAD_REQUEST,
            "G-400-2",
                    "요청 파라미터가 올바르지 않습니다."
    ),
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "AUTH-401-1", "세션이 없거나 만료되었습니다."),
    // 재로그인 외에는 회복 경로가 없다. 클라이언트는 이 코드를 받으면 재시도하지 않는다.
    INVALID_REFRESH_TOKEN(HttpStatus.UNAUTHORIZED, "AUTH-401-3", "세션이 만료되었습니다. 다시 로그인해주세요."),

    // GitHub OAuth (B-FN-001 / GH-AUTH-001). 코드 값은 B조 API 명세서 v1.0을 따른다.
    // AUTH-401-2는 명세에서 "code로 Access Token 교환 실패"에 배정되어 있다. GitJob은
    // 이메일·비밀번호 로그인을 범위에서 제외하므로(GH-AUTH-001) 그 의미로 사용한다.
    OAUTH_REDIRECT_NOT_ALLOWED(HttpStatus.BAD_REQUEST, "AUTH-400-1", "로그인 후 이동할 경로가 허용되지 않습니다."),
    OAUTH_INVALID_STATE(HttpStatus.BAD_REQUEST, "AUTH-400-2", "인증 요청이 유효하지 않습니다. 다시 로그인해 주세요."),
    OAUTH_TOKEN_EXCHANGE_FAILED(HttpStatus.UNAUTHORIZED, "AUTH-401-2", "GitHub 인증에 실패했습니다. 다시 로그인해 주세요."),
    OAUTH_ACCESS_DENIED(HttpStatus.FORBIDDEN, "AUTH-403-3", "GitHub 권한 요청이 거부되었습니다."),
    OAUTH_SCOPE_NOT_GRANTED(HttpStatus.FORBIDDEN, "AUTH-403-4", "저장소 분석에 필요한 권한이 승인되지 않았습니다."),
    OAUTH_GITHUB_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "AUTH-503-1", "GitHub 인증 서버에 연결할 수 없습니다."),

    // 저장소 조회·분석 요청 (B-FN-002). GitHub은 접근 권한이 없는 저장소에도 404를 주며,
    // 그 구분을 우리가 되살리면 비공개 저장소의 존재 여부가 새어 나간다. 그래서 권한 없음과
    // 없는 저장소를 같은 코드로 응답한다.
    GITHUB_TOKEN_INVALID(HttpStatus.UNAUTHORIZED, "AUTH-401-4", "GitHub 연결이 만료되었습니다. 다시 로그인해 주세요."),
    REPOSITORY_NOT_FOUND(HttpStatus.NOT_FOUND, "REPO-404-1", "저장소를 찾을 수 없거나 접근 권한이 없습니다."),
    BRANCH_NOT_FOUND(HttpStatus.NOT_FOUND, "REPO-404-2", "브랜치를 찾을 수 없습니다."),
    REPOSITORY_ACCESS_DENIED(HttpStatus.FORBIDDEN, "REPO-403-1", "저장소를 분석할 권한이 없습니다."),
    // 보관·비활성은 권한 문제가 아니다. 403으로 답하면 사용자가 GitHub 권한 설정을
    // 뒤지게 되므로, 저장소 상태 때문이라는 것이 드러나는 코드를 따로 둔다.
    REPOSITORY_NOT_ANALYZABLE(HttpStatus.CONFLICT, "REPO-409-1", "보관되었거나 비활성화된 저장소는 분석할 수 없습니다."),
    GITHUB_RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "REPO-429-1", "GitHub API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요."),
    GITHUB_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "REPO-503-1", "GitHub API에 연결할 수 없습니다."),

    // Worker 전용 repository credential broker. 외부 세션 JWT와 다른 서비스 토큰을
    // 쓰며, 요청 tuple이 저장된 분석과 정확히 일치할 때만 사용자 토큰을 반환한다.
    INTERNAL_WORKER_UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "INTERNAL-401-1",
            "분석 Worker 인증에 실패했습니다."),
    ANALYSIS_CREDENTIAL_NOT_FOUND(HttpStatus.NOT_FOUND, "INTERNAL-404-1",
            "분석 요청에 해당하는 저장소 자격증명을 찾을 수 없습니다."),
    ANALYSIS_CREDENTIAL_NOT_ACTIVE(HttpStatus.CONFLICT, "INTERNAL-409-1",
            "이미 종료된 분석에는 저장소 자격증명을 발급할 수 없습니다."),
    GITHUB_RECONNECT_REQUIRED(HttpStatus.FAILED_DEPENDENCY, "INTERNAL-424-1",
            "GitHub 연결을 갱신해야 합니다."),

    // 분석 요청은 활성 Registry snapshot 없이 재현 가능한 이벤트를 만들 수 없다.
    REGISTRY_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "ANALYSIS-503-1",
            "현재 분석 기준을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."),
    // 기술 후보 검토 (관리자 화면). 승격은 레지스트리를 바꾸므로 "없는 후보"와
    // "이미 처리된 후보"를 구분해서 알린다. 관리자 둘이 같은 목록을 보고 같은
    // 행을 누르는 것은 오류가 아니라 정상이며, 409를 받은 쪽은 목록을 새로
    // 읽으면 누가 어떻게 처리했는지 그대로 보인다.
    TECHNOLOGY_CANDIDATE_NOT_FOUND(HttpStatus.NOT_FOUND, "ADMIN-404-1", "기술 후보를 찾을 수 없습니다."),
    TECHNOLOGY_CANDIDATE_ALREADY_DECIDED(HttpStatus.CONFLICT, "ADMIN-409-1", "이미 처리된 기술 후보입니다."),
    REGISTRY_DRAFT_EMPTY(HttpStatus.CONFLICT, "ADMIN-409-2", "발행할 레지스트리 초안이 없습니다."),
    INVALID_TECHNOLOGY_ID(HttpStatus.BAD_REQUEST, "ADMIN-400-1", "기술 식별자 형식이 올바르지 않습니다."),

    // 근거 조회. ANALYSIS_NOT_FOUND 는 위(AN-404-1)에 이미 있으므로 다시 만들지
    // 않는다 -- 같은 뜻의 코드가 둘이면 화면이 어느 쪽으로 분기해야 할지 알 수 없다.
    TECHNOLOGY_NOT_IN_REGISTRY(HttpStatus.NOT_FOUND, "EVD-404-2", "레지스트리에 없는 기술입니다."),

    // C 계산 결과 조회 (S15P21E102-279). 계산 대기·미준비·표본 부족은 여기 없다 --
    // 그것들은 오류가 아니라 200 응답의 dataStatus 로 내려간다. 오류 코드는 사용자가
    // 무언가 해야 하거나(목표 직무 선택) 아무것도 할 수 없는 경우(장애)에만 쓴다.
    TARGET_ROLE_NOT_SELECTED(HttpStatus.NOT_FOUND, "MATCH-404-1", "목표 직무를 먼저 선택해 주세요."),
    // 없는 결과와 남의 결과를 구분하지 않는다. 구분하면 다른 사용자의 Snapshot 존재
    // 여부가 새어 나간다 -- C 도 같은 이유로 둘 다 404 를 준다.
    MATCHING_RESULT_NOT_FOUND(HttpStatus.NOT_FOUND, "MATCH-404-2", "매칭 결과를 찾을 수 없습니다."),
    MATCHING_CRITERIA_INVALID(HttpStatus.BAD_REQUEST, "MATCH-400-1", "지원하지 않는 직무 또는 필터입니다."),
    // 재시도하면 풀릴 수 있는 상태다. 500 으로 내리면 화면이 재시도를 권하지 못한다.
    COMPUTE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "MATCH-503-1",
            "분석 계산 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."),
    TREND_CRITERIA_INVALID(HttpStatus.BAD_REQUEST, "TREND-400-1", "지원하지 않는 기술 또는 기간입니다.");



    private final HttpStatus httpStatus;
    private final String code;
    private final String message;

}
