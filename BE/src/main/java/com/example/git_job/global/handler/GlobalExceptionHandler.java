package com.example.git_job.global.handler;


import java.util.stream.Collectors;
import java.util.stream.Stream;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import com.example.git_job.global.response.ErrorResponse;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {


    @ExceptionHandler(CustomException.class)
    protected ResponseEntity<ErrorResponse> handleCustomException(CustomException e) {
        ErrorCode errorCode = e.getErrorCode();

        if (errorCode.getHttpStatus().is5xxServerError()) {
            log.error("business error: {}", errorCode.getCode(), e);
        } else {
            log.warn("business error: {}", errorCode.getCode());
        }
        return createErrorResponse(errorCode);
    }

    /**
     * DTO 유효성 검사 실패를 처리한다.
     *
     * <p>{@code BindingResult}를 그대로 기록하면 거절된 값(rejected value)이 함께
     * 남는다. 예를 들어 회원가입에서 짧은 비밀번호가 거절되면 <b>비밀번호 원문이
     * 로그에 유출</b>되므로(1582 금지 사항), 위반한 <b>필드명과 제약 이름만</b>
     * 남긴다.</p>
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    protected ResponseEntity<ErrorResponse> handleValidationException(
            MethodArgumentNotValidException e
    ) {
        // 응답 코드는 1685에서 INVALID_SIGNUP → INVALID_REQUEST_BODY로 확대됐다.
        // 유효성 검사는 회원가입 전용이 아니므로 로그의 errorCode도 같은 값을 쓴다.
        log.warn("validation failed: {}", violatedConstraints(e.getBindingResult()));
        return createErrorResponse(ErrorCode.INVALID_REQUEST_BODY);
    }

    /**
     * 본문이 JSON으로 해석되지 않는 요청(문법 오류, 타입 불일치 등)을 처리한다.
     * 클라이언트 입력 오류이므로 500이 아니라 400으로 응답해야 한다.
     *
     * <p>예외 메시지에는 파서가 실패한 위치의 <b>원본 본문 조각</b>이 포함될 수 있어
     * 비밀번호 같은 값이 로그로 새어 나갈 수 있다. 그래서 메시지 대신 원인 예외의
     * 타입만 남긴다. 타입만으로도 문법 오류와 타입 불일치를 구분할 수 있다.</p>
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    protected ResponseEntity<ErrorResponse> handleMessageNotReadable(
            HttpMessageNotReadableException e
    ) {

        log.warn(
                "malformed request body: {}",
                e.getMostSpecificCause().getClass().getSimpleName()
        );
        return createErrorResponse(ErrorCode.INVALID_REQUEST_BODY);
    }

    /**
     * 위반된 제약을 {@code 필드명:제약이름} 형태로 요약한다.
     * 거절된 값과 메시지 템플릿은 값이 섞일 수 있으므로 포함하지 않는다.
     */
    private String violatedConstraints(BindingResult bindingResult) {
        if (bindingResult == null) {
            return "unknown";
        }
        Stream<String> fieldViolations = bindingResult.getFieldErrors().stream()
                .map(error -> error.getField() + ":" + error.getCode());
        Stream<String> objectViolations = bindingResult.getGlobalErrors().stream()
                .map(error -> error.getObjectName() + ":" + error.getCode());
        return Stream.concat(fieldViolations, objectViolations)
                .distinct()
                .collect(Collectors.joining(", "));
    }

    private ResponseEntity<ErrorResponse> createErrorResponse(ErrorCode errorCode) {
        return ResponseEntity
                .status(errorCode.getHttpStatus())
                .body(ErrorResponse.of(errorCode));
    }


}

