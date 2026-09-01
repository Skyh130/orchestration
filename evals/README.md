# 트리거 테스트

이 디렉터리는 Claude Code 스킬의 자동 검증 시스템을 관리합니다. 각 스킬에 대해 "이 문장에서 스킬이 켜져야 하는가"를 판정자(Claude)에게 물어보고, 실제 판정과 기대값을 비교해 통과율을 측정합니다. 처음부터 끝까지 자동화되어 있어 CI/CD에 물릴 수 있습니다.

## 폴더 구조

```
evals/
├── dev-kickoff/
│   ├── triggers.json      # 입력 파일: 쿼리 목록
│   └── results.json       # 출력 파일: 상세 결과 (JSON)
│   └── results.md         # 출력 파일: 요약 및 표 (마크다운)
├── 다른-스킬/
│   ├── triggers.json
│   └── results.json / results.md
└── README.md              # 이 파일
```

스킬마다 하나의 하위 폴더가 있습니다. 각 폴더에는 입력 파일(`triggers.json`)과 출력 파일(`results.json`, `results.md`)이 들어갑니다.

## 실행 방법

### 기본 명령

```bash
python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
    --skill-file .claude/skills/dev-kickoff/SKILL.md
```

### 옵션 설명

| 옵션 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `query_file` | ✓ | - | 테스트할 쿼리 목록 JSON 파일의 경로 |
| `--skill-file` | ✓ | - | 판정할 스킬의 SKILL.md 파일 경로 |
| `--workers` | | 5 | 동시에 실행할 판정 수 (conductor의 동시 실행 상한 3~5와 맞춤) |
| `--timeout` | | 180 | 각 판정의 타임아웃 (초) |
| `--threshold` | | 0.8 | 통과 기준 통과율 (이 값 미만이면 종료 코드 1) |
| `--out-dir` | | `query_file` 폴더 | 결과 파일을 쓸 디렉터리 |

### 실행 예

```bash
# 기본 설정으로 실행
python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
    --skill-file .claude/skills/dev-kickoff/SKILL.md

# 동시 실행 수를 늘리고 타임아웃을 줄임
python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
    --skill-file .claude/skills/dev-kickoff/SKILL.md \
    --workers 10 --timeout 120

# 통과율 기준을 70%로 낮춤
python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
    --skill-file .claude/skills/dev-kickoff/SKILL.md \
    --threshold 0.7
```

## triggers.json 형식

### 최상위 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `skill_name` | 문자열 | 테스트하는 스킬의 이름 |
| `note` | 문자열 | 테스트 설계에 대한 설명 (선택사항) |
| `queries` | 배열 | 테스트 쿼리 목록 |

### queries 배열의 각 항목 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | 정수 | 테스트 케이스 번호 |
| `should_trigger` | 불린 | 이 쿼리에서 스킬이 켜져야 하는지 여부 (`true` 또는 `false`) |
| `query` | 문자열 | 사용자가 입력하는 텍스트 |

### 예시

```json
{
  "skill_name": "dev-kickoff",
  "note": "켜져야 할 문장 10개 + 켜지면 안 되는 문장 10개",
  "queries": [
    {"id": 1, "should_trigger": true, "query": "새로운 프로젝트를 시작하려는데 뭐부터 해야 할지 모르겠어"},
    {"id": 2, "should_trigger": false, "query": "이 함수 좀 리팩터링 해줘"}
  ]
}
```

## 결과 읽는 법

스크립트를 실행하면 두 파일이 생성됩니다.

### results.json

전체 판정 결과를 JSON 형식으로 저장합니다. 각 쿼리에 대한 상세 정보가 들어 있습니다.

### results.md

마크다운 형식의 요약 및 결과 표입니다. 주요 지표들:

- **통과 (pass_rate)**: 기대값과 판정이 일치한 테스트의 비율
  - 분모는 API 오류 등으로 판정하지 못한 테스트를 **제외**합니다
  - 예: "통과: 18/20 (90%)"

- **판정 실패 (errors)**: API 오류나 타임아웃으로 판정하지 못한 테스트 건수
  - 이 건수는 통과율 계산에서 **제외**됩니다
  - "통과율이 무엇을 뜻하는지 명확하게" 하기 위함입니다

- **켜져야 할 때 켜진 비율 (recall_should_trigger)**: 
  - 켜져야 하는 경우(`should_trigger: true`) 중에서 실제로 켜진 비율
  - "재현율(Recall)" 또는 "참양성률"
  - 예: "켜져야 할 때 켜진 비율: 80%"

- **켜지면 안 될 때 안 켜진 비율 (precision_should_not_trigger)**:
  - 켜지면 안 되는 경우(`should_trigger: false`) 중에서 실제로 켜지지 않은 비율
  - "정확도(Precision)" 또는 "참음성률"
  - 예: "켜지면 안 될 때 안 켜진 비율: 100%"

결과 표는 각 테스트의 ID, 기대값, 실제 판정, 통과/실패 여부, 쿼리 미리보기를 보여줍니다.

## 종료 코드

스크립트는 다음과 같이 종료합니다.

| 종료 코드 | 조건 |
|----------|------|
| 0 | 통과율이 `--threshold` 이상 (기본값 80% 이상) |
| 1 | 통과율이 `--threshold` 미만 |

따라서 CI/CD 파이프라인에서 다음과 같이 사용할 수 있습니다.

```bash
python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
    --skill-file .claude/skills/dev-kickoff/SKILL.md \
    --threshold 0.8

if [ $? -ne 0 ]; then
  echo "트리거 테스트 실패"
  exit 1
fi
```
