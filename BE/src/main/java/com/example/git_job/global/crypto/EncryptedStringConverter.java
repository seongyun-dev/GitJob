package com.example.git_job.global.crypto;

import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;
import java.nio.charset.StandardCharsets;
import org.springframework.security.crypto.encrypt.BytesEncryptor;
import org.springframework.stereotype.Component;

/**
 * 문자열 컬럼을 저장 직전에 암호화하고 읽을 때 복호화한다.
 *
 * <p>엔티티의 필드 타입은 {@code String} 그대로이고 컬럼만 {@code BYTEA}가 된다.
 * 그래서 이 값을 쓰는 코드는 암호화를 알 필요가 없다.</p>
 *
 * <h2>이 컬럼으로는 조회할 수 없다</h2>
 *
 * <p>암호화할 때마다 난수 IV가 붙으므로 같은 평문도 매번 다른 바이트가 된다.
 * {@code WHERE access_token_enc = ?} 같은 조건은 절대 맞지 않고, 인덱스도
 * 의미가 없다. 조회 키로 쓸 값에는 이 변환기를 붙이면 안 된다.</p>
 *
 * <h2>복호화 실패를 삼키지 않는다</h2>
 *
 * <p>키가 바뀌었거나 다른 환경의 값이 섞였거나 행이 변조되면 예외가 난다.
 * {@code null}을 돌려주면 호출자는 "토큰이 없다"로 읽고 사용자에게 재로그인을
 * 시키는데, 그러면 잘못된 키로 새 값이 덮여 쓰이고 설정 오류는 끝까지 드러나지
 * 않는다. 시끄럽게 실패하는 편이 맞다.</p>
 *
 * <p>Hibernate 가 이 변환기를 Spring 빈으로 받아 가므로({@code SpringBeanContainer})
 * 생성자 주입이 동작한다. 기본 생성자가 없는 것은 의도한 것이다 -- 컨테이너 밖에서
 * 만들어지면 암호기가 없는 채로 조용히 동작하는 대신 즉시 실패한다.</p>
 */
@Converter
@Component
public class EncryptedStringConverter implements AttributeConverter<String, byte[]> {

    private final BytesEncryptor encryptor;

    public EncryptedStringConverter(BytesEncryptor encryptor) {
        this.encryptor = encryptor;
    }

    @Override
    public byte[] convertToDatabaseColumn(String attribute) {
        if (attribute == null) {
            return null;
        }
        return encryptor.encrypt(attribute.getBytes(StandardCharsets.UTF_8));
    }

    @Override
    public String convertToEntityAttribute(byte[] dbData) {
        if (dbData == null) {
            return null;
        }
        try {
            return new String(encryptor.decrypt(dbData), StandardCharsets.UTF_8);
        } catch (RuntimeException failure) {
            // 원인 값은 남기지 않는다. 암호문 조각이라도 로그로 나가면 안 된다.
            throw new IllegalStateException(
                    "암호화된 컬럼을 복호화하지 못했습니다. AES_SYMMETRIC_KEY·AES_SALT가 "
                            + "이 데이터를 쓴 값과 같은지 확인하십시오.", failure);
        }
    }
}
