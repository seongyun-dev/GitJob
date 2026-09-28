package com.example.git_job.analysis.domain;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.regex.Pattern;

/**
 * 사용자가 보낸 {@code owner/repo}와 브랜치 이름을 GitHub URL에 넣기 전에 검증한다.
 *
 * <p>이 값들은 그대로 경로가 되므로 {@code ..}를 허용하면 다른 엔드포인트로 빠져나갈 수
 * 있다. 인코딩만으로는 부족하고, 형식 자체를 여기서 좁힌다.</p>
 */
public record RepositoryCoordinate(String owner, String repository, String branch) {

    /** GitHub 계정명 규칙: 영숫자와 하이픈, 39자 이하. */
    private static final Pattern OWNER = Pattern.compile("^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$");
    private static final Pattern REPOSITORY = Pattern.compile("^[A-Za-z0-9_.-]{1,100}$");

    public RepositoryCoordinate {
        owner = require(owner, OWNER);
        repository = require(repository, REPOSITORY);
        branch = requireBranch(branch);
    }

    /** {@code owner/repo} 한 덩어리로 받은 입력을 쪼갠다. 슬래시는 정확히 하나여야 한다. */
    public static RepositoryCoordinate of(String fullName, String branch) {
        if (fullName == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        int separator = fullName.indexOf('/');
        if (separator < 0 || separator != fullName.lastIndexOf('/')) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        return new RepositoryCoordinate(
                fullName.substring(0, separator), fullName.substring(separator + 1), branch);
    }

    public String fullName() {
        return owner + "/" + repository;
    }

    private static String require(String value, Pattern pattern) {
        if (value == null || !pattern.matcher(value).matches()) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        return value;
    }

    /**
     * 브랜치 이름은 {@code feature/cdc}처럼 슬래시를 포함할 수 있어 다른 두 값보다 넓게
     * 받는다. 대신 Git이 금지하는 형태(공백, 제어문자, {@code ..}, 슬래시로 시작·끝)를
     * 막는다. 여기를 통과한 값만 URL 경로에 이어 붙인다.
     */
    private static String requireBranch(String value) {
        if (value == null || value.isBlank() || value.length() > 255
                || !value.equals(value.strip())
                || value.contains("..")
                || value.startsWith("/") || value.endsWith("/")
                || value.startsWith("-")) {
            throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
        }
        for (char character : value.toCharArray()) {
            if (character < 0x20 || character == 0x7F
                    || character == ' ' || character == '~' || character == '^'
                    || character == ':' || character == '?' || character == '*'
                    || character == '[' || character == '\\' || character == '#') {
                throw new CustomException(ErrorCode.INVALID_REQUEST_BODY);
            }
        }
        return value;
    }
}
