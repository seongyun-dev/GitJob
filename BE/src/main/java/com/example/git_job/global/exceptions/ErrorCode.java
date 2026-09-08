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
    GITHUB_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "REPO-503-1", "GitHub API에 연결할 수 없습니다.");



    private final HttpStatus httpStatus;
    private final String code;
    private final String message;

}
