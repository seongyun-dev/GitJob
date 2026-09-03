package com.example.git_job.global.response;


import com.example.git_job.global.exceptions.ErrorCode;
import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
public class ErrorResponse {

    private final String code;        // ErrorCode에서 관리하는 커스텀 에러 번호 (예: 4001, 4002 등)
    private final String message; // 프론트엔드에게 보여줄 에러 메시지

    public static ErrorResponse of(ErrorCode errorCode) {
        return ErrorResponse.builder()
                .code(errorCode.getCode())
                .message(errorCode.getMessage())
                .build();
    }

}
