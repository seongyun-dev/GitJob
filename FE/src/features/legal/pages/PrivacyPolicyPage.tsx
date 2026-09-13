import type { ReactNode } from 'react'
import { PageHero } from '@/shared/ui/PageHero'
import { TEAM_EMAIL, TEAM_NAME } from '@/shared/constants/team'

/**
 * 개인정보 처리방침 · 하단바에서 들어온다.
 *
 * 문구를 지어내지 않았다. 수집 항목은 실제로 저장하는 열에서 읽었고
 * (`BE/src/main/java/com/example/git_job/auth/domain/User.java`), 분석 범위와
 * private 저장소 취급은 저장소 `README.md`에 팀이 적어 둔 원칙 그대로다.
 * 처리방침은 사실 진술이라 화면을 채우려고 항목을 늘리면 그 자체가 거짓이 된다.
 *
 * 그래서 흔히 들어가는 다음 항목은 **일부러 비웠다.**
 *   - 사업자 정보·대표자·주소: 사업자가 아니다. SSAFY 교육 프로젝트다.
 *   - 제3자 제공·국외 이전·처리 위탁: 현재 코드에 해당 경로가 없다.
 *   - 쿠키·광고 식별자: 세션 쿠키 외에 추적 목적의 저장을 하지 않는다.
 *
 * 보관 기간과 파기 절차는 팀이 아직 정하지 않았다. 임의의 숫자(`3년` 같은)를 적으면
 * 지키지 못할 약속이 되므로, 정해지지 않았다는 사실을 그대로 적었다.
 * TODO: 팀에서 보관·파기 기준을 확정하면 9절을 그 값으로 교체하고 시행일을 넣는다.
 */

/** 절 하나. 번호와 제목을 붙이는 방식이 모든 절에서 같아야 해서 컴포넌트로 둔다. */
function Article({
  index,
  title,
  children,
}: {
  index: number
  title: string
  children: ReactNode
}) {
  return (
    <section className="border-t border-brand-line pt-6">
      <h2 className="text-[15px] font-[750] tracking-[-0.02em] text-brand-ink">
        제{index}조 {title}
      </h2>
      <div className="mt-3 max-w-[74ch] text-[13.5px] leading-[1.85] break-keep text-brand-body">
        {children}
      </div>
    </section>
  )
}

/** 본문 안의 항목 목록. 근거 나열이 많아 같은 모양을 반복해 쓴다. */
function Items({ items }: { items: readonly string[] }) {
  return (
    <ul className="mt-2 flex flex-col gap-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2">
          <span className="mt-[0.7em] h-[3px] w-[3px] shrink-0 rounded-full bg-brand-faint" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

export function PrivacyPolicyPage() {
  return (
    <div className="flex flex-col gap-9">
      <PageHero
        eyebrow="PRIVACY"
        title="개인정보 처리방침"
        description={`${TEAM_NAME} 팀이 GitJob을 운영하면서 어떤 정보를 어떤 목적으로 다루는지 적었습니다.`}
      />

      {/*
        상단 고지. 이 서비스의 성격을 먼저 밝히지 않으면 아래 내용이 상용 서비스의
        약관처럼 읽힌다. 톤 토큰 `caution`은 배지 체계의 색이지만 여기서는 배지가
        아니라 고지 상자라 배경만 쓰고 글자는 본문 색을 유지한다.
      */}
      <div className="rounded-[14px] border border-brand-line bg-tone-caution-bg/60 px-5 py-4">
        <p className="text-[13px] leading-[1.75] break-keep text-brand-body">
          GitJob은 SSAFY 교육 과정에서 만든 프로젝트이며 상용 서비스가 아닙니다. 아래
          내용은 현재 구현된 동작을 기준으로 적었고, 기능이 바뀌면 함께 고칩니다.
        </p>
      </div>

      <Article index={1} title="수집하는 개인정보">
        GitHub 계정으로 로그인할 때 GitHub가 전달하는 정보 중 아래 항목을 저장합니다.
        별도의 회원가입 절차나 직접 입력 받는 항목은 없습니다.
        <Items
          items={[
            'GitHub 계정 고유 번호와 로그인 아이디',
            '이름, 이메일, 프로필 이미지 주소',
            '로그인할 때 허용한 GitHub 권한 범위',
            '저장소 조회에 사용하는 GitHub 액세스 토큰',
            '계정 생성 시각과 마지막 수정 시각',
          ]}
        />
      </Article>

      <Article index={2} title="수집하지 않는 정보">
        비밀번호를 받지 않습니다. 인증은 GitHub OAuth에만 의존하므로 GitHub 계정의
        비밀번호가 GitJob에 전달되지 않습니다. 결제 정보, 연락처, 위치 정보도 받지
        않습니다.
      </Article>

      <Article index={3} title="이용 목적">
        <Items
          items={[
            '로그인한 사용자를 식별하고 본인의 분석 결과만 보여주기 위해',
            '분석할 수 있는 GitHub 저장소 목록을 불러오기 위해',
            '선택한 저장소에서 기술 사용 근거를 찾아 결과로 저장하기 위해',
            '문의를 주신 경우 답변하기 위해',
          ]}
        />
        위 목적 외로 쓰지 않으며, 목적이 늘어나면 이 문서를 먼저 고칩니다.
      </Article>

      <Article index={4} title="저장소 분석의 범위">
        분석은 <strong className="font-[750] text-brand-ink">사용자가 선택한 저장소</strong>에
        대해서만 이루어지며 읽기 전용입니다. 저장소의 내용을 수정하거나 새로 만들지
        않습니다. 선택하지 않은 저장소는 목록에 이름이 보이더라도 분석하지 않습니다.
      </Article>

      <Article index={5} title="private 저장소의 취급">
        private 저장소에서 만들어진 근거는 해당 사용자 본인의 결과 조회에만 쓰입니다.
        전체 기술 트렌드 집계에는 공개된 집계 데이터만 사용하며,{' '}
        <strong className="font-[750] text-brand-ink">
          private 저장소의 원문은 시장 트렌드에 사용하지 않습니다.
        </strong>
      </Article>

      <Article index={6} title="GitHub 액세스 토큰의 보관">
        토큰은 데이터베이스에 암호화해 저장하며 화면이나 응답으로 다시 내보내지
        않습니다. GitHub 설정에서 GitJob의 권한을 직접 회수할 수 있고, 회수하면 저장된
        토큰으로는 더 이상 저장소를 읽을 수 없습니다.
      </Article>

      <Article index={7} title="제3자 제공과 처리 위탁">
        수집한 개인정보를 제3자에게 제공하지 않습니다. 광고나 분석 목적의 외부 도구에
        전달하지 않으며, 국외로 이전하지 않습니다.
      </Article>

      <Article index={8} title="이용자의 권리">
        본인의 정보에 대해 열람·정정·삭제를 요청할 수 있습니다. 아래 주소로 요청하시면
        확인 후 처리합니다. GitHub 측 권한 회수는 GitHub 계정 설정에서 직접 하실 수
        있습니다.
        <a
          href={`mailto:${TEAM_EMAIL}`}
          className="mt-3 inline-block text-[14px] font-[750] tracking-[-0.01em] text-brand-600 hover:underline"
        >
          {TEAM_EMAIL}
        </a>
      </Article>

      <Article index={9} title="보관 기간과 파기">
        {/*
          이 절만 값이 아니라 상태를 적는다. 위의 파일 주석 참고 — 정해지지 않은 기간을
          지어 쓰지 않는다.
        */}
        보관 기간과 파기 절차는 아직 확정하지 않았습니다. 확정 전까지는 삭제 요청을
        받으면 개별적으로 처리하며, 기준이 정해지면 이 문서에 기간과 절차를 명시하고
        시행일을 함께 적겠습니다.
      </Article>

      <Article index={10} title="문의">
        개인정보 처리에 관한 문의는 {TEAM_NAME} 팀 대표 메일{' '}
        <a
          href={`mailto:${TEAM_EMAIL}`}
          className="font-[750] text-brand-600 hover:underline"
        >
          {TEAM_EMAIL}
        </a>
        로 받습니다.
      </Article>
    </div>
  )
}
