package com.example.git_job.global.crypto;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor.CipherAlgorithm;
import org.springframework.security.crypto.keygen.KeyGenerators;

/**
 * 변환기 자체의 성질을 고정한다.
 *
 * <p>여기서 확인하는 세 가지는 저장 방식이 바뀌어도 유지돼야 하는 것들이다.
 * 평문이 컬럼에 남지 않는 것, 같은 값이 매번 다른 바이트가 되는 것, 변조된
 * 바이트가 조용히 다른 문자열로 읽히지 않는 것.</p>
 */
class EncryptedStringConverterTest {

    private static final String TOKEN = "gho_16C7e42F292c6912E7710c838347Ae178B4a";

    /** 운영과 같은 설정. 기본 생성자는 CBC + 고정 IV라 이 테스트가 통과하지 못한다. */
    private static AesBytesEncryptor encryptor(String key) {
        return new AesBytesEncryptor(
                key, "5c0744940b5c369b", KeyGenerators.secureRandom(16), CipherAlgorithm.GCM);
    }

    private final EncryptedStringConverter converter =
            new EncryptedStringConverter(encryptor("a".repeat(64)));

    @Test
    @DisplayName("넣은 값을 그대로 되돌려준다")
    void whatGoesInComesBackOut() {
        byte[] stored = converter.convertToDatabaseColumn(TOKEN);

        assertEquals(TOKEN, converter.convertToEntityAttribute(stored));
    }

    @Test
    @DisplayName("컬럼에는 평문이 남지 않는다")
    void theColumnDoesNotContainThePlaintext() {
        // 이 테스트가 이 변경의 전부다. 나머지는 이것이 깨지지 않게 하는 장치다.
        byte[] stored = converter.convertToDatabaseColumn(TOKEN);

        assertFalse(new String(stored, StandardCharsets.UTF_8).contains("gho_"));
        assertFalse(Arrays.equals(TOKEN.getBytes(StandardCharsets.UTF_8), stored));
    }

    @Test
    @DisplayName("같은 토큰도 매번 다른 바이트가 된다")
    void thesameTokenEncryptsDifferentlyEveryTime() {
        // 결정적이면 토큰이 같은 두 사용자가 DB에서 그대로 드러나고, 어떤 행이
        // 언제 안 바뀌었는지도 보인다. 난수 IV가 그것을 막는다.
        byte[] first = converter.convertToDatabaseColumn(TOKEN);
        byte[] second = converter.convertToDatabaseColumn(TOKEN);

        assertFalse(Arrays.equals(first, second));
        assertEquals(TOKEN, converter.convertToEntityAttribute(first));
        assertEquals(TOKEN, converter.convertToEntityAttribute(second));
    }

    @Test
    @DisplayName("한 바이트만 바뀌어도 복호화가 실패한다")
    void aTamperedRowIsRejected() {
        // GCM 인증 태그가 하는 일이다. CBC였다면 깨진 평문이 조용히 나올 수 있다.
        byte[] stored = converter.convertToDatabaseColumn(TOKEN);
        byte[] tampered = stored.clone();
        tampered[tampered.length - 1] ^= 0x01;

        assertThrows(IllegalStateException.class,
                () -> converter.convertToEntityAttribute(tampered));
    }

    @Test
    @DisplayName("다른 키로 쓴 값은 조용히 null이 되지 않고 실패한다")
    void aValueFromAnotherKeyFailsLoudly() {
        // null을 돌려주면 호출자는 "토큰이 없다"로 읽고 재로그인을 시킨다. 그러면
        // 잘못된 키로 새 값이 덮여 쓰이고 설정 오류는 끝까지 드러나지 않는다.
        byte[] fromAnotherEnvironment =
                new EncryptedStringConverter(encryptor("b".repeat(64)))
                        .convertToDatabaseColumn(TOKEN);

        assertThrows(IllegalStateException.class,
                () -> converter.convertToEntityAttribute(fromAnotherEnvironment));
    }

    @Test
    @DisplayName("null은 null 그대로 둔다")
    void nullStaysNull() {
        // 토큰이 없는 사용자가 있다. 여기서 빈 문자열로 바꾸면 "토큰이 있는데
        // 비어 있다"가 되어 재로그인 안내 대신 GitHub 호출이 401로 실패한다.
        assertNull(converter.convertToDatabaseColumn(null));
        assertNull(converter.convertToEntityAttribute(null));
    }

    @Test
    @DisplayName("빈 문자열도 왕복한다")
    void anEmptyStringSurvivesTheRoundTrip() {
        byte[] stored = converter.convertToDatabaseColumn("");

        assertEquals("", converter.convertToEntityAttribute(stored));
    }

    @Test
    @DisplayName("여러 스레드가 같은 암호기를 써도 값이 섞이지 않는다")
    void concurrentUseDoesNotMixValues() throws Exception {
        // AesBytesEncryptor는 Cipher 인스턴스를 재사용하고 encrypt/decrypt를
        // synchronized로 감싼다. 싱글턴 빈으로 공유하므로 그 전제를 고정해 둔다.
        var threads = new Thread[8];
        var results = new String[threads.length];
        for (int i = 0; i < threads.length; i++) {
            String value = TOKEN + i;
            int slot = i;
            threads[i] = new Thread(() -> {
                for (int round = 0; round < 50; round++) {
                    byte[] stored = converter.convertToDatabaseColumn(value);
                    results[slot] = converter.convertToEntityAttribute(stored);
                }
            });
            threads[i].start();
        }
        for (Thread thread : threads) {
            thread.join();
        }

        for (int i = 0; i < threads.length; i++) {
            assertEquals(TOKEN + i, results[i]);
        }
    }
}
