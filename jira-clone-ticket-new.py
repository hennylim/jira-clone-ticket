import json
import JiraClient
from dotenv import load_dotenv
import os
import argparse
from pathlib import Path
import sys
import re

# Optional translator setup (googletrans). If unavailable, fallback to original text
try:
    from googletrans import Translator  # type: ignore
    _translator = Translator()
except Exception:
    _translator = None

def contains_japanese(text):
    # Detect Hiragana, Katakana, CJK Unified Ideographs, Half-width Katakana
    if not text:
        return False
    jp_pattern = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]")
    return bool(jp_pattern.search(text))

def translate_ja_to_ko(text):
    if not text or _translator is None:
        return text
    try:
        result = _translator.translate(text, src='ja', dest='ko')
        return result.text if getattr(result, 'text', None) else text
    except Exception:
        return text

def translate_japanese_segments_to_korean(text):
    """Translate only segments that contain Japanese characters; keep others (e.g., English) as-is."""
    if not text or _translator is None:
        return text
    # Helper to detect Japanese character
    def _is_japanese_char(ch):
        return bool(re.match(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]", ch))

    # Segment the text into runs of Japanese vs non-Japanese
    segments = []  # list of (segment_text, is_japanese)
    current_chars = []
    current_is_jp = None
    for ch in text:
        ch_is_jp = _is_japanese_char(ch)
        if current_is_jp is None:
            current_is_jp = ch_is_jp
            current_chars.append(ch)
            continue
        if ch_is_jp == current_is_jp:
            current_chars.append(ch)
        else:
            segments.append(("".join(current_chars), current_is_jp))
            current_chars = [ch]
            current_is_jp = ch_is_jp
    if current_chars:
        segments.append(("".join(current_chars), current_is_jp))

    # Translate only Japanese segments
    translated_segments = []
    for seg_text, is_jp in segments:
        if is_jp and seg_text.strip():
            try:
                result = _translator.translate(seg_text, src='ja', dest='ko')
                translated_segments.append(result.text if getattr(result, 'text', None) else seg_text)
            except Exception:
                translated_segments.append(seg_text)
        else:
            translated_segments.append(seg_text)
    return "".join(translated_segments)

def sanitize_double_quotes(text):
    """Remove ASCII double-quote characters from text."""
    if text is None:
        return text
    return text.replace('"', '').strip()

def make_clone_summary_description(jira_client, issue):
    org_key = issue.get("key")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = jira_client.extract_description_text(issue)
    if contains_japanese(summary):
        translated_summary = translate_japanese_segments_to_korean(summary)
        summary = translated_summary if translated_summary else summary
    # Remove any double quotes from the final summary
    summary = sanitize_double_quotes(summary)
    summary = f"Clone-{summary}({org_key})"
    return summary, description, org_key

def get_issue_info(jira_client, issue):
    org_key = issue.get("key")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = jira_client.extract_description_text(issue)
    return summary, description, org_key

# jira 리스트를 입력 받아 화면에 출력하는 함수, 출려시 티켓번호 - summary 출력 한다. 티켓 번호 출력 여부를 인자롤 받는다. 
# 마지막에 티켓 수를 출력한다. 리스트 앞 뒤 구분선을 출력한다. 
def print_jira_list(jira_client, issues, print_ticket_num=False):
    for i, issue in enumerate(issues):
        if print_ticket_num:
            print(f"{i+1}. {issue.get('key')} - {issue.get('fields').get('summary')}")
        else:
            print(f"{issue.get('key')} - {issue.get('fields').get('summary')}")
    print("--------------------------------")
    print(f"티켓 수: {len(issues)}")


# 검색된 jira 티켓 리스트를 입력받아 리스트를 화면에 전체 리스트를 출력하고, 사용자는 출력된 리스트에서 선택을 하고 선택된 티켓 리스트를 반환하는 함수
# 사용자가 다중 선택을 할 수 있도록 함수
def select_jira_ticket(jira_client, issues):
    selected_issues = []
    selected_issues_num_list = []

    for i, issue in enumerate(issues):
        print(f"{i+1}. {issue.get('key')} - {issue.get('fields').get('summary')}")   

    print("--------------------------------")
    selected_issues_num_list = input("선택할 티켓 번호를 입력하세요: ").strip()  # 사용자가 선택한 티켓 번호를 입력받음
    
    # 입력이 비어있는 경우 처리
    if not selected_issues_num_list:
        print("선택된 티켓이 없습니다.")
        return selected_issues
        
    selected_issues_num_list = selected_issues_num_list.split(',')
    try:
        for num in selected_issues_num_list:
            num = num.strip()  # 공백 제거
            if not num:  # 빈 문자열 건너뛰기 (예: "1,,2" 입력 시)
                continue
            index = int(num) - 1
            if index < 0 or index >= len(issues):
                print(f"경고: {num}번은 유효하지 않은 티켓 번호입니다. 건너뜁니다.")
                continue
            selected_issues.append(issues[index])
    except ValueError:
        print("경고: 숫자가 아닌 값이 입력되었습니다. 유효한 티켓 번호만 처리합니다.")

    print("--------------------------------")
    print("선택된 티켓 리스트")
    print("--------------------------------")
    print_jira_list(jira_client, selected_issues, print_ticket_num=True)
    
    return selected_issues  


if __name__ == "__main__":
    # 인자 파싱
    parser = argparse.ArgumentParser(description="Jira Clone Ticket")
    parser.add_argument('-c', '--config', type=str, help="Path to JSON config file")
    # 기존 파라미터들도 그대로 지원 (충돌 시 CLI가 우선)
    parser.add_argument('-jql', '--jql', type=str, help="JQL query to execute (e.g., 'project = SI')")
    parser.add_argument('-e', "--env", type=str, help="Path to .env file (default: .env)")
    parser.add_argument('-pj', '--clone_project_key', type=str, help="Clone target 프로젝트의 key")
    parser.add_argument('-cl', '--clone_label', type=str, nargs='+', help='생성할 티켓의 레이블 (공백으로 구분)')
    parser.add_argument('-cm', '--clone_models', type=str, nargs='+', help='생성할 티켓의 모델 (공백으로 구분)')
    parser.add_argument('-du', '--due_date', type=str, help='Due date (YYYY-MM-DD) or After n Weeks (nW) or After n Days (nD)')
    parser.add_argument('-t', '--issue_type', type=str, help='Bug/Task')
    # Single issue clone mode: provide a single issue key
    parser.add_argument('-k', '--issue_key', type=str, help='단일 원본 이슈 키 (예: PROJ-123)')
    parser.add_argument('-pk', '--parent_key', type=str, help='상위 이슈 키 (예: PROJ-123)')


    args = parser.parse_args()

    # JSON 설정 로드 (옵션)
    config = {}
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"지정된 JSON 설정 파일이 존재하지 않습니다: {config_path}")
            sys.exit(1)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"JSON 설정 파일을 읽는 중 오류가 발생했습니다: {e}")
            sys.exit(1)

    # 설정 병합 (CLI 우선)
    jql = args.jql if args.jql else config.get('jql')
    clone_project_key = args.clone_project_key if args.clone_project_key else config.get('clone_project_key')
    # clone_label은 CLI가 우선, 없으면 JSON에서 읽고 문자열이면 분해
    if args.clone_label is not None:
        clone_label = args.clone_label
    else:
        clone_label = config.get('clone_label')
        if isinstance(clone_label, str):
            clone_label = [label for label in clone_label.split() if label]
    due_date = args.due_date if args.due_date else config.get('due_date')
    issue_type = args.issue_type if args.issue_type else config.get('issue_type')
    issue_key = args.issue_key if args.issue_key else config.get('issue_key')
    # clone_models은 CLI가 우선, 없으면 JSON에서 읽고 문자열이면 분해
    if args.clone_models is not None:
        clone_models = args.clone_models
    else:
        clone_models = config.get('clone_models')
        if isinstance(clone_models, str):
            clone_models = [label for label in clone_models.split() if label]
    parent_key = args.parent_key if args.parent_key else config.get('parent_key')

    # due_date가 숫자+W 경우 숫자와 문자를 분리
    due_date_tmp = 0
    
    if due_date and due_date[-1] == 'W':
        due_date_tmp = due_date[:-1]        
        
        # 입력받은 due_date_tmp 가 0 보다 큰 경우 오늘 날자로 부터 due_date_tmp week 만큼 뒤의 날자를 due_date에 대입.
        if int(due_date_tmp) > 0:
            from datetime import datetime, timedelta
            due_date = (datetime.now() + timedelta(weeks=int(due_date_tmp))).strftime('%Y-%m-%d')
    elif due_date and due_date[-1] == 'D': #D는 날자
        due_date_tmp = due_date[:-1]

        # 입력받은 due_date_tmp 가 0 보다 큰 경우 오늘 날자로 부터 due_date_tmp day 만큼 뒤의 날자를 due_date에 대입.
        if int(due_date_tmp) > 0:
            from datetime import datetime, timedelta
            due_date = (datetime.now() + timedelta(days=int(due_date_tmp))).strftime('%Y-%m-%d')

    # 필수 설정 검증 (병합 후)
    missing = []
    # Either jql or issue_key must be provided
    if not (jql or issue_key):
        missing.append('jql or issue_key')
    if not clone_project_key:
        missing.append('clone_project_key')
    if not clone_label:
        missing.append('clone_label')
    if not due_date:
        missing.append('due_date')
    if not issue_type:
        missing.append('issue_type')
    if not clone_models:
        missing.append('clone_models')
    if missing:
        print(f"필수 입력 누락: {', '.join(missing)}. CLI 옵션 또는 JSON 설정으로 값을 제공하세요.")
        sys.exit(1)

    # .env 파일 로드 (CLI > JSON > 기본값)
    env_value = args.env if args.env is not None else config.get('env', '.env')
    env_path = Path(env_value)
    if not env_path.exists():
        print(f"지정된 .env 파일이 존재하지 않습니다: {env_path}")
        sys.exit(1)

    load_dotenv(dotenv_path=env_path)

    # 환경 변수 불러오기
    base_url = os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_EMAIL")
    api_token = os.getenv("JIRA_API_TOKEN")

    if not all([base_url, email, api_token]):
        print("환경변수 JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN이 누락되었습니다.")
        sys.exit(1)

    # Jira 클라이언트 인스턴스 생성
    jira_client = JiraClient.JiraClient(base_url, email, api_token)
    selected_issues = []
    if issue_key:
        # Single issue clone mode
        print(f"단일 이슈 키로 클론을 진행합니다: {issue_key}")
        issue = jira_client.get_issue(issue_key)
        if not issue:
            print(f"지정된 이슈를 찾을 수 없습니다: {issue_key}")
            sys.exit(1)
        selected_issues = [issue]
    else:
        # JQL search mode
        issues = jira_client.search_issues_excpt_head_by_jql(jql, 'Clone-')
        print(f"검색된 티켓 수: {len(issues)}")

        #검색된 티켓이 없을 경우 종료
        if len(issues) == 0:
            sys.exit(0)
        
        selected_issues = select_jira_ticket(jira_client, issues)
        
        #선택된 티켓이 없을경우 종료
        if len(selected_issues) == 0:
            sys.exit(0)

    print("--------------------------------")
    #사용자에게 생성 여부를 물어본다. 
    create_ticket = input("생성하시겠습니까? (y/n): ")
    if create_ticket == "y":
        print("생성을 시작합니다.")
        for issue in selected_issues:
            summary, description, org_key = make_clone_summary_description(jira_client, issue)
            
            # 동일한 summary를 가진 티켓이 있는지 검사
            print("동일한 summary를 가진 티켓이 있는지 검사...")
            print(f"summary: {summary}")
            existing_issues = jira_client.search_issues_by_summary(clone_project_key, summary)
            if existing_issues:
                print(f"Warning: {summary} - {org_key} 와 동일한 summary를 가진 티켓이 이미 존재합니다. 생성을 건너뜁니다.")
                continue
                
            print(f"{summary} - {org_key} 생성중...")
            new_issue_key = jira_client.clone_issue_with_media_upload(
                                source_issue_key=org_key,
                                project_key=clone_project_key,
                                summary=summary,
                                issue_type=issue_type,
                                due_date=due_date,
                                labels=clone_label,
                                models=clone_models,
                                parent_key=parent_key
                            )
            if not new_issue_key:
                print(f"Warning: {summary} - {org_key} 생성 실패")
                continue
            print(f"{summary} - {org_key} 생성 완료")



    else:
        print("생성을 취소합니다.")
        sys.exit(0) 
    
