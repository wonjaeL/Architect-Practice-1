# 수업 전 준비

수강생은 Codex CLI에 미리 로그인하고, 강사는 전원을 원본 저장소의 collaborator로 등록합니다. 수강생 PC에서 Git 인증과 `user.name`·`user.email`도 설정해 둡니다. 시작 도구는 계정 설정을 입력받지 않습니다.

## 자동 채점과 전체 결과
`main`에 이 변경을 반영한 후 저장소 Settings → Pages → Source를 **GitHub Actions**로 선택합니다. Actions에서 **Grade practice submissions**를 한 번 실행해 빈 결과 화면을 준비합니다. 포크에서는 Actions도 먼저 활성화합니다. `github-pages` 환경의 배포 브랜치 규칙에 `students/*`를 허용합니다.

이후 `students/*`의 제출 ZIP push가 자동 채점을 시작합니다. 5분 주기 수집과 수동 실행도 지원합니다. 수강생 코드와 테스트는 네트워크·인증 정보가 없는 일회용 컨테이너에서 실행합니다. 원본 테스트, 제출 테스트, 운영 규정에서 작성한 쿠폰 검사 24개를 통과하면 `results` 브랜치에 채점 영수증을 기록하고 GitHub Pages를 갱신합니다. 기존 외부 채점기를 대체하는 별도 구현이므로 수업 전에 규정과 검사 범위를 검토합니다.

전체 화면은 참가자·실행 순으로 표시하며, 통과한 동일 조건의 기본 실행과만 절감률을 계산합니다. 채점 파일의 제출 blob과 소스 체크섬이 일치해야 `python lab.py sync`에 반영됩니다. 변경하지 않은 제출은 재채점하지 않습니다.

포크로 운영하면 준비된 각 PC의 `config.json`에서 `repository`도 해당 포크 URL로 맞춥니다. 전체 결과 주소는 `https://<소유자>.github.io/Architect-Practice-1/`입니다. 원본 저장소에는 이 PR 병합과 위 설정이 필요합니다.

## 공통 환경

Python 3.10 이상, Git, 수업용 Codex CLI를 설치하고 각 PC에서 실행합니다.

```bash
git clone https://github.com/legenduck/Architect-Practice-1.git
cd Architect-Practice-1
python start.py --prepare --model <수업용_모델명> --reasoning-effort high
python start.py doctor
```

Windows에서는 `py -3`, macOS/Linux에서는 `python3`를 사용할 수 있습니다. 모델·추론 설정·CLI 버전·전역 지침은 수업 전체에서 동일하게 맞춥니다. `--prepare`는 패키지와 작업 폴더를 준비하며 기존 지침을 보존합니다. 참가자 번호도 미리 넣으려면 `--participant p01`을 추가합니다. `config.json`과 `.venv`는 PC별로 준비하며 Git에 포함되지 않습니다.

## 준비 확인

`doctor`는 도구·모델 설정·기존 Codex 로그인·샌드박스 파일 입출력과 테스트·Git 제출 접속·채점 결과 수신 경로를 확인합니다. 참가자 번호 입력, 브랜치 전환, 커밋, push, 모델 호출은 하지 않습니다. 결과는 짧게 표시하고 상세 오류는 `doctor.log`에 남깁니다. 강사는 학생 점검 전에 아래 자동 채점을 한 번 실행해야 합니다.

GitHub 등록과 PC의 Git 인증은 별도이므로 실제 수강생 계정으로 점검합니다. 샌드박스 오류가 나면 해당 PC의 실행 환경을 정비합니다. 모델 접근 권한과 중앙 채점 동작은 모델을 호출하지 않는 `doctor`만으로 확인할 수 없으므로, 배포 전에 기본 지침 실행 → 제출 → 채점 수신을 한 번 완료합니다.

## 수강생 흐름

`start.bat` 또는 `start.command` 실행 → 최초 참가자 번호 입력 → 메뉴에서 실습을 반복합니다. 메뉴는 실행 후에도 유지되며, 제출 후 채점을 기다리지 않고 다음 실험을 진행할 수 있습니다. 제출 실패는 같은 기록으로 재시도합니다. 실습 중에는 로그인이나 Git 계정 설정을 진행하지 않습니다.

회귀 테스트: `python -m unittest discover -s tests_lab -v`. 대체 CLI와 로컬 Git 저장소로 실행 흐름을 검증하며, 배포할 OS와 실제 모델·중앙 채점 환경은 별도로 확인합니다.
