# 수업 전 준비

수강생은 Codex CLI에 미리 로그인하고, 강사는 전원을 원본 저장소의 collaborator로 등록합니다. 수강생 PC에서 Git 인증과 `user.name`·`user.email`도 설정해 둡니다. 시작 도구는 계정 설정을 입력받지 않습니다.

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

`doctor`는 도구·모델 설정·기존 Codex 로그인·샌드박스 파일 입출력과 테스트·Git 제출 접속을 확인합니다. 참가자 번호 입력, 브랜치 전환, 커밋, push, 모델 호출은 하지 않습니다. 결과는 짧게 표시하고 상세 오류는 `doctor.log`에 남깁니다.

GitHub 등록과 PC의 Git 인증은 별도이므로 실제 수강생 계정으로 점검합니다. 샌드박스 오류가 나면 해당 PC의 실행 환경을 정비합니다. 모델 접근 권한과 중앙 채점 동작은 모델을 호출하지 않는 `doctor`만으로 확인할 수 없으므로, 배포 전에 기본 지침 실행 → 제출 → 채점 수신을 한 번 완료합니다.

## 수강생 흐름

`start.bat` 또는 `start.command` 실행 → 최초 참가자 번호 입력 → 메뉴에서 실습을 반복합니다. 메뉴는 실행 후에도 유지되며, 제출 후 채점을 기다리지 않고 다음 실험을 진행할 수 있습니다. 제출 실패는 같은 기록으로 재시도합니다. 실습 중에는 로그인이나 Git 계정 설정을 진행하지 않습니다.

회귀 테스트: `python -m unittest discover -s tests_lab -v`. 대체 CLI와 로컬 Git 저장소로 실행 흐름을 검증하며, 배포할 OS와 실제 모델·중앙 채점 환경은 별도로 확인합니다.
