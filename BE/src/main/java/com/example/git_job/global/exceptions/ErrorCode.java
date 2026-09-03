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
    );


    private final HttpStatus httpStatus;
    private final String code;
    private final String message;

}
