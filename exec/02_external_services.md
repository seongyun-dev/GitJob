# 외부 서비스 가입 및 설정 가이드

이 문서는 GitJob 실행·배포·데이터 수집에 필요한 외부 서비스만 정리한다. 비밀번호, PEM, 토큰의 실제 값은 포함하지 않는다.

## 1. 필수 서비스

### 1.1 GitLab

- 주소: `https://lab.ssafy.com`
- 용도: 소스 저장소, Merge Request, Jenkins SCM checkout
- 프로젝트: `s15-bigdata-dist-sub1/S15P21E102`
- 준비 항목: 개인 액세스 토큰 또는 Project Access Token
- 최소 권한: clone/pull만 할 때 `read_repository`; MR API 자동화까지 할 때 `api`
- Jenkins 등록: Username with password, ID `gitjob-gitlab-scm`

토큰을 저장소 URL, `.env`, Jenkinsfile에 직접 기록하지 않는다.

### 1.2 GitHub OAuth App

- 용도: 사용자의 GitHub 로그인 및 비공개 저장소 접근 동의
- 생성 위치: GitHub Settings → Developer settings → OAuth Apps
- Homepage URL: `https://j15e102.p.ssafy.io`
- Authorization callback URL: `https://j15e102.p.ssafy.io/api/v1/auth/github/callback`
- 발급 값: Client ID, Client Secret
- 서버 변수: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_REDIRECT_URI`
- 요청 scope: `read:user`, `repo`

callback URL은 대소문자, 경로, scheme까지 완전히 일치해야 한다. Secret은 서비스 EC2의 `.env.service`에만 저장한다.

### 1.3 GitHub API Token

- 용도: collector가 GitHub REST/GraphQL API로 저장소 메타데이터와 파일을 수집
- 서버 변수: `GITHUB_API_TOKEN`
- 공개 저장소만 수집하면 인증 없이도 가능하지만 rate limit이 매우 낮아 토큰 사용을 권장한다.
- 비공개 저장소 수집 시 classic PAT은 `repo`가 필요하다. Fine-grained token은 대상 저장소를 지정하고 Metadata/Contents read 권한을 부여한다.
- OAuth 로그인용 Client Secret과 수집용 API Token은 목적이 다르므로 분리한다.

팀원 개인 토큰 하나를 모든 환경에 공유하지 말고, 운영용 전용 토큰을 만들고 만료일과 교체 담당자를 기록한다.

### 1.4 SSAFY EC2 및 SSH

- 서비스 서버: `J15E102`, `ubuntu@j15e102.p.ssafy.io`
- 데이터 서버: `J15E102A`, `ubuntu@j15e102a.p.ssafy.io`
- 용도: 서비스와 데이터 인프라 실행
- 준비 항목: 서버별 PEM 개인키
- 제약: AWS Console 계정 없이 SSH로만 관리

PEM은 Jenkins SSH Credential과 담당자 PC의 안전한 키 저장소에만 둔다. 저장소와 메신저에 업로드하지 않는다.

### 1.5 Tailscale

- 용도: 두 EC2 간 비공개 통신, 관리자 UI 접근, GPU/LLM 서버 연결
- 준비 항목: 팀 Tailscale 계정 또는 초대, 각 장치 등록
- 서비스 EC2 주소: `100.71.215.74`
- 데이터 EC2 주소: `100.70.66.38`

DB, Redis, Kafka, Jenkins, HDFS, Spark 관리 포트를 공인 주소로 노출하지 않는다. 장치 교체 시 ACL과 등록된 장치 목록을 함께 정리한다.

현재 GPU 요약 서버는 별도 애플리케이션 인증이 없으므로 Tailscale ACL을 서비스 노드에서 필요한 포트로만 제한해야 한다.

## 2. 데이터 수집 서비스

### 2.1 GH Archive

- 주소: `https://www.gharchive.org/`, 데이터: `https://data.gharchive.org`
- 용도: 시간 단위 공개 GitHub 이벤트를 받아 기술 트렌드 후보를 계산
- 가입/API key: 불필요
- 주의: 아직 공개되지 않은 월/시간 파일은 재시도만 반복하지 않도록 수집 기간과 존재 여부를 확인한다.

### 2.2 채용 사이트

수집 대상은 JobKorea, Saramin, Work24, GameJob, Career다. 현재 collector는 별도 파트너 API 계정 없이 공개 페이지를 수집한다.

- 사이트별 HTML 구조 변경 시 parser가 깨질 수 있다.
- robots 정책, 이용약관, 요청 빈도를 준수한다.
- JobKorea 일부 데이터는 OCR 경로를 사용하므로 PaddleOCR/PaddlePaddle 이미지 빌드가 필요하다.
- 사이트 로그인 정보나 쿠키를 소스에 저장하지 않는다.
- GameJob, Career, JobKorea 수집은 공식 파트너 API가 아니라는 위험이 저장소 문서에 남아 있으므로, 운영 지속 전 서비스 약관과 법적 허용 범위를 다시 확인한다.

## 3. 배포·실행에 필요한 공개 저장소

다음 서비스는 일반적으로 별도 가입 없이 패키지/이미지를 다운로드하지만, 장애 또는 rate limit에 대비해 캐시를 권장한다.

| 서비스 | 용도 |
|---|---|
| Docker Hub / Quay.io | PostgreSQL, Redis, Kafka, Hadoop, Nginx, Debezium, 모니터링 이미지 |
| Maven Central / Gradle services | Backend 의존성 및 Gradle wrapper |
| npm registry | Frontend 의존성 |
| PyPI | Python worker/collector 의존성 |
| Paddle 공식 wheel index | OCR용 PaddlePaddle |

사설 Registry는 현재 사용하지 않는다. Jenkins가 각 EC2에서 직접 이미지를 빌드한다.

## 4. TLS와 도메인

- 현재 서비스 도메인: SSAFY 제공 `j15e102.p.ssafy.io`
- 인증서: Let's Encrypt/Certbot으로 발급된 인증서를 Nginx 컨테이너에 mount
- Cafe24에서 구입한 `gitjob.shop`: 현재 서비스 종료 정책에 따라 Nginx에서 차단

인증서 갱신 시 대상 도메인의 DNS가 서비스 EC2를 가리키는지 확인하고, 갱신 후 Nginx가 새 인증서를 읽도록 reload 또는 recreate한다.

## 5. LLM/GPU 서버

- 용도: 규칙 엔진 결과(Fact Pack)를 자연어 설명으로 생성
- 형태: 별도 GPU 서버의 Ollama/요약 API
- Jenkins 기본 배포 포함 여부: 포함하지 않음
- 준비 항목: Tailscale 연결, 모델 다운로드, 서비스 EC2/worker에서 접근 가능한 내부 URL

외부 상용 LLM API 가입은 현재 필수 조건이 아니다. GPU 서버의 모델명과 endpoint는 환경 변수로 관리한다.

## 6. 선택 서비스

Jira와 Notion은 이슈·문서 협업 도구로 사용 가능하지만 애플리케이션 빌드 또는 실행에는 필요하지 않다. Jenkins, Grafana, Prometheus, Kafka UI, RedisInsight는 프로젝트가 직접 호스팅하므로 외부 가입 서비스가 아니다.

SSAFY Mattermost Incoming Webhook은 선택 사항이다. EC2 health 변화 알림에 사용하며 URL은 `/etc/gitjob/health-probe.env`의 `HEALTH_ALERT_WEBHOOK`에만 저장한다. 비워도 health probe 자체는 실행된다.
