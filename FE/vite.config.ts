import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  /*
   * 세 번째 인수가 `''`인 이유는 `VITE_` 접두가 없는 값도 읽기 위해서다. 아래
   * 프록시 대상은 **개발 서버(Node)만** 쓰는 값이고 브라우저 번들에 들어가면 안 된다.
   */
  const env = loadEnv(mode, process.cwd(), '')

  /*
   * 프록시 대상. 기본은 로컬 백엔드다.
   *
   * 배포된 백엔드로 붙여 보려면 `FE/.env.local`(gitignore 대상)에 한 줄 적는다.
   *
   *     VITE_API_PROXY_TARGET=https://gitjob.shop
   *
   * 주소를 이 파일에 박지 않는 이유는 둘이다. 추적되는 설정에 운영 호스트가 들어가면
   * 받는 사람의 기본 동작이 조용히 바뀌고, 로컬 백엔드를 띄운 사람이 왜 자기 서버로
   * 안 가는지 찾아야 한다.
   */
  const apiTarget = env.VITE_API_PROXY_TARGET ?? 'http://localhost:8080'

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      // 세션 쿠키를 같은 오리진으로 주고받기 위해 개발 서버에서 프록시한다.
      // 이렇게 해야 CORS 없이 credentials: 'include' 가 동작한다.
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          /*
           * 원격 백엔드가 내려주는 세션 쿠키는 자기 도메인(`gitjob.shop`)으로 온다.
           * 그대로 두면 브라우저가 `localhost`에서 받은 쿠키의 도메인이 맞지 않아
           * 버리고, 로그인한 것처럼 보이다가 다음 요청에서 401이 난다.
           */
          cookieDomainRewrite: 'localhost',
        },
      },
    },
  }
})
