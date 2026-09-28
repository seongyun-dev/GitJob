package com.example.git_job.global.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor.CipherAlgorithm;
import org.springframework.security.crypto.keygen.KeyGenerators;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
public class PasswordConfig {

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /**
     * 저장 시 암호화용. 지금은 GitHub Access Token 한 곳이 쓴다.
     *
     * <p>GCM 과 난수 IV 를 <b>명시한다.</b> 인자 두 개짜리 생성자는 CBC 에
     * {@code NULL_IV_GENERATOR}(0으로 채운 고정 IV)를 쓰는데, 그러면 같은 평문이
     * 언제나 같은 암호문이 된다. 토큰이 같은 두 행이 DB 에서 그대로 드러나고,
     * 어떤 행이 언제 바뀌지 않았는지도 보인다.</p>
     *
     * <p>CBC 는 무결성도 보장하지 않는다. GCM 은 128비트 인증 태그를 붙이므로
     * 한 바이트만 바뀌어도 복호화가 실패한다 -- 조용히 다른 값이 나오지 않는다.</p>
     *
     * <p><b>알고리즘을 바꾸면 이미 저장된 값은 읽을 수 없다.</b> 바꿔야 한다면
     * 재암호화 마이그레이션이 함께 필요하다.</p>
     */
    @Bean
    public AesBytesEncryptor aesBytesEncryptor(
            @Value("${encryption.symmetric-key}") String symmetricKey,
            @Value("${encryption.salt}") String salt
    ) {
        return new AesBytesEncryptor(
                symmetricKey, salt, KeyGenerators.secureRandom(16), CipherAlgorithm.GCM);
    }
}
