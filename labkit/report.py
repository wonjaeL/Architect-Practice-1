from __future__ import annotations

import json
from pathlib import Path


def eligible(run: dict) -> bool:
    return (
        run.get("execution_status") == "completed"
        and run.get("comparison_valid", False)
        and run.get("grade", {}).get("status") == "passed"
        and type(run.get("usage", {}).get("input_tokens")) is int
    )


def display_status(run: dict) -> dict:
    execution = run.get("execution_status")
    submitted = run.get("submission_status")
    grade = run.get("grade", {})
    if submitted == "failed":
        submission = "제출 실패"
    elif submitted == "submitted" or grade.get("artifact_blob"):
        submission = "제출됨"
    else:
        submission = "미제출"
    grade_label = {"passed": "통과", "failed": "실패", "error": "채점 오류"}.get(
        grade.get("status")
    )
    if grade_label is None:
        grade_label = "채점 대기" if submission == "제출됨" else "채점 전"
    return {
        "execution": {
            "prepared": "실행 준비",
            "completed": "실행 종료",
            "failed": "실행 실패",
            "no_changes": "구현 변경 없음",
            "timeout": "시간 초과",
            "interrupted": "중단",
            "error": "실행 오류",
        }.get(execution, "상태 미확인"),
        "submission": submission,
        "grade": grade_label,
    }


def render_report(root: Path) -> Path:
    runs = []
    for path in sorted((root / "runs").glob("*/summary.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if (
            path.parent / "github-status.json"
        ).exists() and "submission_status" not in run:
            run["submission_status"] = "submitted"
        run["display"] = display_status(run)
        run["logs"] = [
            name
            for name in ("last-message.txt", "codex-stderr.txt", "events.jsonl")
            if (path.parent / name).exists()
        ]
        runs.append(run)
    # JSON is embedded in HTML; escape script terminators and markup characters.
    payload = (
        json.dumps(runs, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>실습 1 실행 결과</title><style>
body{font:18px/1.7 system-ui,sans-serif;max-width:1250px;margin:45px auto;padding:0 25px;color:#202329}
h1{font-size:34px}h2{margin-top:45px;font-size:25px}a{color:#4169e1}table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:12px;border-bottom:1px solid #ddd}th{border-top:2px solid #222}
.bar{height:27px;background:#4169e1;min-width:1px;display:inline-block;vertical-align:middle;margin-right:10px}
.muted{color:#646b75}.bad{color:#ad2727}.good{color:#176a49}select{font:inherit;max-width:100%;padding:7px}
pre{background:#f4f5f7;padding:20px;overflow:auto;white-space:pre-wrap;font-size:14px}.chartrow{margin:12px 0}
</style><h1>실습 1 실행 결과</h1>
<p>채점에 통과한 실행끼리 입력 토큰을 비교합니다. 기록은 실행 순서로 표시하며 순위를 매기지 않습니다.</p>
<p class="muted">수정 후 이 파일을 다시 열거나 새로고침하세요. 과제 구현에 사용한 토큰만 집계하며 지침 수정 대화는 제외합니다.</p>
<p class="muted">실행 종료는 기능 완성이나 채점 통과를 뜻하지 않습니다. 오류 또는 구현 변경 없음이면 최종 응답과 실행 로그를 확인하세요.</p>
<table><thead><tr><th>실행</th><th>작업 지침</th><th>실행 상태</th><th>입력 토큰</th><th>제출</th><th>채점</th><th>비교</th></tr></thead><tbody id="rows"></tbody></table>
<h2>총 입력 토큰과 채점 결과</h2><div id="totals"></div>
<p class="muted">회색 막대는 채점 대기, 실패 또는 측정 오류로 비교에서 제외된 실행입니다. 조건이 다른 실행도 서로 비교하지 않습니다.</p>
<h2>호출별 입력 토큰</h2><label>실행 선택 <select id="pick"></select></label><div id="calls"></div>
<h2>명령에 나타난 문서 경로</h2><p class="muted">명령 문자열에서 발견한 경로입니다. 문서 전체를 실제로 읽었는지나 와일드카드로 연 파일까지 확정하는 목록은 아닙니다. 원본 명령 기록과 함께 확인합니다.</p><div style="overflow-x:auto"><table id="docmatrix"></table></div><div id="docs"></div>
<h2>선택한 실행의 진단과 로그</h2><div id="logs"></div><pre id="detail"></pre>
<script>const runs=__DATA__;
const el=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
const group=[...runs].reverse().find(r=>r.execution_status==='completed'&&r.condition_id)?.condition_id;
const eligible=r=>r.execution_status==='completed'&&r.comparison_valid&&r.condition_id===group&&r.grade?.status==='passed'&&Number.isInteger(r.usage?.input_tokens);
const matrix=document.querySelector('#docmatrix'),header=el('tr');header.append(el('th','문서 경로'));
runs.forEach((r,i)=>header.append(el('th',(i+1)+' / '+r.label)));matrix.append(header);
for(const path of [...new Set(runs.flatMap(r=>r.usage.document_candidates))].sort()){const row=el('tr');row.append(el('td',path));for(const r of runs)row.append(el('td',r.usage.document_candidates.includes(path)?'확인':'기록 없음'));matrix.append(row);}
const max=Math.max(1,...runs.map(r=>r.usage?.input_tokens||0));
for(const r of runs){const row=el('tr');const a=el('a',r.id);a.href='runs/'+encodeURIComponent(r.id)+'/summary.json';const td=el('td');td.append(a);row.append(td);
for(const text of [r.label,r.display.execution,r.usage.input_tokens??'미측정',r.display.submission,r.display.grade,eligible(r)?'가능':r.condition_id&&group&&r.condition_id!==group?'조건 다름':'제외'])row.append(el('td',String(text)));document.querySelector('#rows').append(row);
const line=el('div');line.className='chartrow';line.append(el('span',r.label+' '));if(Number.isInteger(r.usage.input_tokens)){const b=el('span');b.className='bar';b.style.width=(r.usage.input_tokens/max*60)+'%';if(!eligible(r))b.style.background='#a4a8b0';line.append(b,el('span',r.usage.input_tokens.toLocaleString()));}else line.append(el('span','입력 토큰 미측정'));document.querySelector('#totals').append(line);
const opt=el('option',r.id+' / '+r.label);opt.value=r.id;document.querySelector('#pick').append(opt);}
function show(){const r=runs.find(x=>x.id===document.querySelector('#pick').value);if(!r)return;const area=document.querySelector('#calls');area.replaceChildren();
if(!r.usage.calls.length)area.append(el('p','이 로그에는 검증 가능한 호출별 사용량이 없습니다. 실행 총량을 호출 수로 나누어 추정하지 않습니다.'));
else{const mx=Math.max(1,...r.usage.calls);r.usage.calls.forEach((v,i)=>{const d=el('div');d.className='chartrow';const b=el('span');b.className='bar';b.style.width=v/mx*60+'%';d.append(el('span',(i+1)+'회 '),b,el('span',v.toLocaleString()));area.append(d);});}
const docs=document.querySelector('#docs');docs.replaceChildren();for(const p of r.usage.document_candidates)docs.append(el('div',p));if(!r.usage.document_candidates.length)docs.append(el('p','기록된 명령에서 문서 경로를 찾지 못했습니다. 문서를 읽지 않았다는 뜻은 아닙니다.'));
const logs=document.querySelector('#logs');logs.replaceChildren();for(const name of r.logs){const a=el('a',name);a.href='runs/'+encodeURIComponent(r.id)+'/'+name;const line=el('div');line.append(a);logs.append(line);}
document.querySelector('#detail').textContent=JSON.stringify({conditions:r.conditions,execution_status:r.execution_status,error:r.error,exit_code:r.exit_code,submission_status:r.submission_status,submission_error:r.submission_error,grade:r.grade,comparison_message:r.comparison_message,measurement:r.usage.usage_source,measurement_message:r.measurement_message,techniques:r.techniques,note:r.note,commands:r.usage.commands},null,2);}
document.querySelector('#pick').onchange=show;if(runs.length){document.querySelector('#pick').value=runs.at(-1).id;show();}else document.querySelector('#rows').append(el('tr','실행 기록이 없습니다.'));
</script></html>"""
    path = root / "results.html"
    path.write_text(template.replace("__DATA__", payload), encoding="utf-8")
    return path
