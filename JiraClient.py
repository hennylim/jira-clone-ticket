import requests
from requests.auth import HTTPBasicAuth
import json
import os
import sys
from dotenv import load_dotenv
import argparse
from pathlib import Path


class JiraClient:
    def __init__(self, base_url, email, api_token):
        self.base_url = base_url.rstrip('/')
        self.auth = HTTPBasicAuth(email, api_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _handle_response(self, response, success_msg="", failure_msg=""):
        if response.ok:
            if success_msg:
                print(success_msg)
            return response
        else:
            print(f"{failure_msg} Status code: {response.status_code}, Response: {response.text}")
            return None

    def add_comment(self, issue_key, comment):
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        payload = json.dumps({
            "body": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"text": comment, "type": "text"}]
                }]
            }
        })
        response = requests.post(url, headers=self.headers, auth=self.auth, data=payload)
        return self._handle_response(response, f"Comment added to issue {issue_key}.", f"Failed to add comment to issue {issue_key}.")

    def attach_file(self, issue_key, file_path):
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/attachments"
        headers = self.headers.copy()
        # Fix: Do not send JSON Content-Type when uploading multipart/form-data
        # Remove Content-Type so requests can set proper multipart boundary
        headers.pop("Content-Type", None)
        headers["X-Atlassian-Token"] = "no-check"

        try:
            with open(file_path, 'rb') as f:
                # Explicitly provide filename to ensure proper upload metadata
                files = {'file': (os.path.basename(file_path), f)}
                response = requests.post(url, headers=headers, auth=self.auth, files=files)
                return self._handle_response(response, f"File '{file_path}' attached to issue {issue_key}.", f"Failed to attach file to issue {issue_key}.")
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return None

    def add_comment_with_attachment(self, issue_key, comment, file_path):
        comment_resp = self.add_comment(issue_key, comment)
        file_resp = self.attach_file(issue_key, file_path)
        return comment_resp, file_resp

    def get_issue(self, issue_key):
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        response = requests.get(url, headers=self.headers, auth=self.auth)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to get issue details. Status code: {response.status_code}, Response: {response.text}")
            return None

    def get_project_issue_types(self, project_key):
        """
        Fetch createmeta for a project to get allowed issue types (id/name).
        Returns a list of dicts: [{"id": str, "name": str}, ...]
        """
        url = f"{self.base_url}/rest/api/3/issue/createmeta?projectKeys={project_key}&expand=projects.issuetypes"
        response = requests.get(url, headers=self.headers, auth=self.auth)
        if not response.ok:
            print(f"Failed to fetch createmeta for project {project_key}: {response.status_code}, {response.text}")
            return []
        data = response.json() or {}
        projects = data.get("projects", [])
        if not projects:
            return []
        issuetypes = projects[0].get("issuetypes", [])
        return [{"id": it.get("id"), "name": it.get("name")} for it in issuetypes if it]

    def create_issue(self, project_key, summary, issue_type, description=None, due_date=None, labels=None, linked_issue_key=None, models=None):
        """
        [KO] Jira 이슈를 생성하고, 필요 시 기존 이슈의 설명/첨부/링크를 복제합니다.
        - description이 비어 있고 linked_issue_key가 주어지면, 원본 이슈의 설명(ADF 또는 일반 텍스트)을 안전하게 반영합니다.
        - 원본 설명이 ADF이며 media 노드(첨부/이미지 등)가 포함된 경우, 생성 시에는 텍스트만 사용하고 생성 후 원본 ADF로 업데이트합니다.

        [EN] Create a Jira issue and optionally clone description/attachments/link from an existing issue.
        - If description is empty and linked_issue_key is provided, safely reuse source issue's description (ADF or plain text).
        - When the source description is ADF with media nodes, use text-only on create, then update with original ADF after creation.

        Params:
            project_key (str): Jira 프로젝트 키
            summary (str): 이슈 요약
            issue_type (str): 이슈 타입 이름 (e.g., "Task")
            description (dict|str|None): ADF 또는 일반 텍스트 설명. None이면 linked_issue에서 가져올 수 있음
            due_date (str|None): 마감일 (YYYY-MM-DD)
            labels (list[str]|None): 라벨 목록
            linked_issue_key (str|None): 설명/첨부/링크를 복제할 원본 이슈 키
            models (list[str]|None): 모델 목록
        """
        url = f"{self.base_url}/rest/api/3/issue"  # [KO] 이슈 생성 REST API 엔드포인트 / [EN] Issue create endpoint
        
        # [KO] description이 비어 있고 linked_issue_key가 있으면, 원본 이슈의 description을 가져와 복제 준비
        # [EN] If description is None and linked_issue_key is provided, fetch source description to reuse
        original_desc = None
        if description is None and linked_issue_key:
            linked_issue = self.get_issue(linked_issue_key)
            if linked_issue and 'fields' in linked_issue and 'description' in linked_issue['fields']:
                original_desc = linked_issue['fields']['description']
                
                if isinstance(original_desc, dict):
                    # [KO] 원본이 ADF(dict)인 경우: 생성 단계에서는 그대로 쓰면 media 노드로 400 오류가 날 수 있으므로
                    #      생성 후 업데이트에 사용할 원본을 보관하고, 생성 시에는 안전 처리(아래에서 수행)
                    # [EN] If original is ADF: keep for post-create update to avoid 400 due to media nodes on create
                    description = original_desc
                else:
                    # [KO] 일반 텍스트인 경우: ADF 텍스트 노드로 감싸 생성에 바로 사용 가능
                    # [EN] For plain text: wrap as ADF text node to use directly on create
                    description = {
                        "type": "doc",
                        "version": 1,
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": original_desc or ""
                            }]
                        }]
                    }

        # [KO] 생성 시 description 처리 전략:
        #  - 원본이 ADF이고 media 노드가 있을 수 있으므로, 생성 단계에서는 텍스트만 추출한 ADF로 안전하게 전송
        #  - 생성이 완료되면, 원본 ADF를 그대로 다시 업데이트하여 서식/미디어를 복구
        # [EN] Description strategy on create:
        #  - Send text-only ADF on create to avoid media-related 400 errors
        #  - After creation, update with the original ADF to restore full formatting/media
        def _extract_text_from_adf(node):
            """[KO] ADF 문서에서 표시 가능한 텍스트만 재귀적으로 추출합니다.
            [EN] Recursively extract only visible text from an ADF document.
            """
            if isinstance(node, dict):
                # [KO] media 계열 노드는 전부 무시 (이미지/파일 등)
                # [EN] Skip all media-related nodes (image/file etc.)
                if node.get('type') in ('media', 'mediaSingle', 'mediaGroup'):
                    return ""
                texts = []
                # [KO] 텍스트 노드는 텍스트만 수집 / [EN] Collect text from text nodes
                if node.get('type') == 'text' and 'text' in node:
                    texts.append(str(node['text']))
                for key, value in node.items():
                    texts.append(_extract_text_from_adf(value))
                return "".join(filter(None, texts))
            elif isinstance(node, list):
                return "".join(_extract_text_from_adf(child) for child in node)
            else:
                return ""

        use_description_on_create = description
        if original_desc is not None and isinstance(original_desc, dict):
            plain_text = _extract_text_from_adf(original_desc).strip()
            if not plain_text and linked_issue_key:
                # [KO] 텍스트가 전혀 없지만 필수 필드인 경우를 대비한 플레이스홀더
                # [EN] Fallback placeholder when field is required but no text exists
                plain_text = f"Cloned from {linked_issue_key}"
            use_description_on_create = {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": plain_text
                    }]
                }]
            }

        # [KO] 이슈 타입 해석 및 보정 / [EN] Resolve and validate issue type
        resolved_issuetype = None
        allowed_types = self.get_project_issue_types(project_key)
        # 우선 사용자가 지정한 issue_type을 id 또는 name으로 매칭
        if issue_type:
            # id로 매칭 시도 (숫자 문자열 또는 전부 숫자인 경우)
            itype = str(issue_type).strip()
            if allowed_types and itype.isdigit():
                for it in allowed_types:
                    if str(it.get("id")) == itype:
                        resolved_issuetype = {"id": it.get("id")}
                        break
            # name으로 매칭
            if resolved_issuetype is None and allowed_types:
                lower_name = itype.lower()
                for it in allowed_types:
                    if str(it.get("name", "")).lower() == lower_name:
                        # 가능하면 id 사용
                        if it.get("id"):
                            resolved_issuetype = {"id": it.get("id")}
                        else:
                            resolved_issuetype = {"name": it.get("name")}
                        break

        # 지정한 타입이 유효하지 않으면 원본 이슈 타입으로 보정 시도
        if resolved_issuetype is None and linked_issue_key:
            linked_issue = linked_issue if 'linked_issue' in locals() else self.get_issue(linked_issue_key)
            try:
                src_type = (linked_issue or {}).get('fields', {}).get('issuetype', {})
                src_id = str(src_type.get('id')) if src_type.get('id') else None
                src_name = src_type.get('name')
                if allowed_types:
                    if src_id and any(str(it.get('id')) == src_id for it in allowed_types):
                        resolved_issuetype = {"id": src_id}
                    elif src_name and any(str(it.get('name', '')).lower() == str(src_name).lower() for it in allowed_types):
                        # id 찾기
                        match = next((it for it in allowed_types if str(it.get('name', '')).lower() == str(src_name).lower()), None)
                        if match and match.get('id'):
                            resolved_issuetype = {"id": match.get('id')}
                        else:
                            resolved_issuetype = {"name": src_name}
            except Exception:
                pass

        # 여전히 없으면 첫 번째 허용 타입을 사용 (프로젝트 기본 타입 대체)
        if resolved_issuetype is None:
            if allowed_types:
                first = allowed_types[0]
                resolved_issuetype = {"id": first.get("id")} if first.get("id") else {"name": first.get("name", "Task")}
            else:
                # 마지막 안전장치: 전달된 값을 그대로 사용
                resolved_issuetype = {"name": issue_type or "Task"}

        # [KO] 이슈 생성에 필요한 필드 구성 / [EN] Build fields for issue creation
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": resolved_issuetype,
            "description": use_description_on_create if use_description_on_create else None
        }

        # [KO] 선택적 필드: 마감일 / [EN] Optional: due date
        if due_date:
            fields["duedate"] = due_date
        # [KO] 선택적 필드: 라벨 / [EN] Optional: labels
        if labels:
            fields["labels"] = labels

        #if models:
        #    fields["model(s)"] = models

        payload = json.dumps({"fields": fields})
        response = requests.post(url, headers=self.headers, auth=self.auth, data=payload)  # [KO] 이슈 생성 요청 / [EN] Send create request

        if response.status_code == 201:
            issue_key = response.json().get("key")
            print(f"Issue created successfully: {issue_key}")
            
            if linked_issue_key:
                # [KO] 원본 이슈와의 링크 생성 / [EN] Create link to the source issue
                self.link_issue(issue_key, linked_issue_key)
            
            return issue_key
        else:
            # [KO] 이슈 생성 실패 로그 / [EN] Log failure to create issue
            print(f"Failed to create issue. Status code: {response.status_code}, Response: {response.text}")
            return None

    def link_issue(self, source_issue_key, target_issue_key, link_type="Relates"):
        url = f"{self.base_url}/rest/api/3/issueLink"
        payload = json.dumps({
            "type": {"name": link_type},
            "inwardIssue": {"key": source_issue_key},
            "outwardIssue": {"key": target_issue_key}
        })

        response = requests.post(url, headers=self.headers, auth=self.auth, data=payload)
        return self._handle_response(response, f"Issues linked: {source_issue_key} -> {target_issue_key} ({link_type})", "Failed to link issues.")

    def get_issue_link_types(self):
        url = f"{self.base_url}/rest/api/3/issueLinkType"
        response = requests.get(url, headers=self.headers, auth=self.auth)
        if response.ok:
            return response.json().get("issueLinkTypes", [])
        else:
            print(f"Failed to retrieve link types: {response.status_code}")
            return []

    def search_issues_by_summary(self, project_key, summary_keyword):
        """
        Search for issues in a Jira project that contain a specific keyword in their summary.
        :param project_key: The key of the project where the search will be performed (e.g., "PROJ")
        :param summary_keyword: The keyword to search for in issue summaries
        :return: True if issues with the keyword in summary exist, False otherwise
        """
        # Jira JQL 쿼리 준비
        # 특수 문자 이스케이프 처리
        escaped_summary = summary_keyword
        for char in ['"', '[', ']', '(', ')', '&']:
            escaped_summary = escaped_summary.replace(char, f'\\\{char}')
        jql_query = f'project = "{project_key}" AND summary ~ "{escaped_summary}"'
        #print(f"JQL Query: {jql_query}")
        issues = self.search_issues_by_jql(jql_query)
        if issues:
            print(f"Found {len(issues)} issue(s) with '{summary_keyword}' in summary.")
            return issues
        else:
            print(f"No issues found with '{summary_keyword}' in summary.")
            return issues

    def search_issues_by_label(self, project_key, label):
        """
        Search for issues in a Jira project that have a specific label.
        :param project_key: The key of the project where the search will be performed (e.g., "PROJ")
        :param label: The label to search for in issues
        :return: List of issues with the specified label
        """
        # Jira JQL 쿼리 준비 (POST 기반 공용 메소드 사용)
        jql_query = f'project = "{project_key}" AND labels = "{label}"'
        issues = self.search_issues_by_jql(jql_query)
        if issues:
            print(f"Found {len(issues)} issue(s) with label '{label}'.")
            return issues
        else:
            print(f"No issues found with label '{label}'.")
            return []

    def search_issues_by_jql(self, jql_query, fields=None, max_results=100):
        """
        Execute a JQL search using the POST /rest/api/3/search/jql endpoint.
        This method handles pagination using `nextPageToken` to fetch all matching issues.
        """
        search_url = f"{self.base_url}/rest/api/3/search/jql"
        # 기본 fields 미지정시 최소 필드 지정
        effective_fields = fields if fields is not None else ["summary", "status", "assignee"]

        all_issues = []
        next_page_token = None

        while True:
            payload = {
                "jql": jql_query,
                "maxResults": max_results,
                "fields": effective_fields
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token

            try:
                response = requests.post(search_url, headers=self.headers, auth=self.auth, data=json.dumps(payload))
                if not response.ok:
                    print(f"Failed to search issues. Status code: {response.status_code}, Response: {response.text}")
                    return []

                data = response.json()
                issues = data.get("issues", [])
                all_issues.extend(issues)

                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break  # No more pages

            except requests.exceptions.RequestException as e:
                print(f"An error occurred during JQL search: {e}")
                return []

        print(f"Found {len(all_issues)} issue(s).")
        return all_issues

    def extract_description_text(self, issue_data):
        content = issue_data.get('fields', {}).get('description', {}).get('content', [])
        return "\n".join(
            sub_item.get("text", "")
            for item in content if "content" in item
            for sub_item in item["content"]
            if sub_item.get("type") == "text"
        )

    def get_last_comment_containing(self, issue_key, search_text):
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment"
        response = requests.get(url, headers=self.headers, auth=self.auth)

        if not response.ok:
            print(f"Failed to get comments: {response.status_code}")
            return None

        comments = response.json().get("comments", [])
        for comment in reversed(comments):
            content = comment.get("body", {}).get("content", [])
            comment_text = " ".join(
                item.get("text", "")
                for block in content
                for item in block.get("content", [])
                if item.get("type") == "text"
            )
            if search_text in comment_text:
                return comment_text.strip()

        print(f"No comment containing '{search_text}' found.")
        return None

    def get_linked_issues(self, issue_key):
        """
        Get the list of linked issues for a given issue.
        :param issue_key: The key of the issue (e.g., "PROJ-123")
        :return: List of linked issue keys
        """
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        response = requests.get(url, headers=self.headers, auth=self.auth)

        if not response.ok:
            print(f"Failed to fetch issue details for {issue_key}: {response.status_code}, {response.text}")
            return []

        issue_data = response.json()
        linked_issues = []

        for link in issue_data.get("fields", {}).get("issuelinks", []):
            if "outwardIssue" in link:
                linked_issues.append({
                    "type": link["type"]["name"],
                    "direction": "outward",
                    "issue_key": link["outwardIssue"]["key"],
                    "summary": link["outwardIssue"]["fields"]["summary"]
                })
            elif "inwardIssue" in link:
                linked_issues.append({
                    "type": link["type"]["name"],
                    "direction": "inward",
                    "issue_key": link["inwardIssue"]["key"],
                    "summary": link["inwardIssue"]["fields"]["summary"]
                })

        return linked_issues

    def search_issues_excpt_head_by_jql(self, jql_query, head_str):
        issues = self.search_issues_by_jql(jql_query)
        ret_issues = []
        for issue in issues:
            skip_item = False
            key = issue.get("key")
            summary = issue.get("fields", {}).get("summary", "")
            #print(f"- {key}: {summary}")

            #연결된 이슈 리스트 가져온다.
            linked = self.get_linked_issues(key)
            #print('<<linked issue list :>>')
            for item in linked:
                #print(f"{item['direction']} link ({item['type']}): {item['issue_key']} - {item['summary']}")
                #print(f"{head_str}, {summary}")
                #if  f"{head_str}{summary}" in item['summary']:
                if head_str in item['summary'] and key in item['summary']:
                #if summary in item['summary'] or item['summary'].lower().startswith(head_str):
                    #print(f"found clone item : {item['summary']}")
                    skip_item = True
                    break
            if not skip_item:
                ret_issues.append(issue)
        print(f"New : {len(ret_issues)} issue(s).")
        return ret_issues
    
    # 티켓의 첨부파일을 복사하는 함수
    def copy_attachments(self, issue_key, target_issue_key):
        """첨부파일을 복사하고 첨부파일의 정보를 반환하는 함수
        Note: Jira Cloud does not provide a list-attachments endpoint per issue.
        We must fetch the issue with fields=attachment to enumerate attachments.
        """
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}?fields=attachment"
        response = requests.get(url, headers=self.headers, auth=self.auth)
        copied_attachments = []
        if response.status_code == 200:
            issue_data = response.json() or {}
            attachments = issue_data.get('fields', {}).get('attachment', [])
            for attachment in attachments:
                # 첨부파일 다운로드 URL과 정보 가져오기
                attachment_id = attachment.get('id')
                filename = attachment.get('filename')
                content_url = attachment.get('content')
                
                # 첨부파일 다운로드
                attachment_response = requests.get(content_url, headers=self.headers, auth=self.auth)
                if attachment_response.ok:
                    # 임시 파일로 저장 (디렉토리 보장)
                    temp_dir = os.path.join('temp')
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_path = os.path.join(temp_dir, filename)
                    with open(temp_path, 'wb') as f:
                        f.write(attachment_response.content)
                    
                    # 새 이슈에 첨부
                    attach_response = self.attach_file(target_issue_key, temp_path)
                    if attach_response and attach_response.ok:
                        new_attachment = attach_response.json()[0]  # 새로 생성된 첨부파일 정보
                        copied_attachments.append({
                            'old_id': attachment_id,
                            'new_id': new_attachment.get('id'),
                            'filename': filename,
                            # 새 첨부 다운로드 URL (ADF 링크 대체 시 활용)
                            'content': new_attachment.get('content')
                        })
                    
                    # 임시 파일 삭제
                    os.remove(temp_path)
            
            return copied_attachments
        return []

    def _adf_replace_media_with_attachment_links(self, adf_doc, copied_attachments):
        """
        [KO] ADF 내 media/mediaSingle/mediaGroup 노드를 첨부파일 링크로 치환합니다.
        - 파일명을 기준으로 매칭하고, 실패 시 링크 목록을 추가합니다.
        [EN] Replace media nodes in ADF with hyperlink paragraphs to copied attachments.
        """
        # 파일명 → 첨부 링크 매핑 생성
        filename_to_url = {item.get('filename'): item.get('content') for item in (copied_attachments or []) if item.get('filename') and item.get('content')}

        def make_link_paragraph(filename, url):
            text = filename or 'attachment'
            if not url:
                return {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            return {
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": text,
                    "marks": [{"type": "link", "attrs": {"href": url}}]
                }]
            }

        def transform(node):
            if isinstance(node, dict):
                node_type = node.get('type')
                # mediaSingle: 하나의 media를 감싸는 컨테이너
                if node_type == 'mediaSingle':
                    media = node.get('content', [{}])[0] if node.get('content') else {}
                    filename = media.get('attrs', {}).get('fileName') or media.get('attrs', {}).get('name')
                    url = filename_to_url.get(filename)
                    return make_link_paragraph(filename or 'image', url)
                # mediaGroup: 여러 media를 포함
                if node_type == 'mediaGroup':
                    paragraphs = []
                    for media in node.get('content', []) or []:
                        filename = media.get('attrs', {}).get('fileName') or media.get('attrs', {}).get('name')
                        url = filename_to_url.get(filename)
                        paragraphs.append(make_link_paragraph(filename or 'image', url))
                    return {"type": "paragraph", "content": [{"type": "text", "text": ""}]} if not paragraphs else {"type": "doc", "version": 1, "content": paragraphs}
                # media 자체 노드
                if node_type == 'media':
                    filename = node.get('attrs', {}).get('fileName') or node.get('attrs', {}).get('name')
                    url = filename_to_url.get(filename)
                    return make_link_paragraph(filename or 'image', url)

                # 그 외: 하위 노드 재귀 변환
                new_node = {}
                for k, v in node.items():
                    if k == 'content':
                        if isinstance(v, list):
                            new_node[k] = []
                            for child in v:
                                transformed_child = transform(child)
                                # transform이 doc(여러 문단)으로 돌아오면 펼쳐서 병합
                                if isinstance(transformed_child, dict) and transformed_child.get('type') == 'doc' and isinstance(transformed_child.get('content'), list):
                                    new_node[k].extend(transformed_child['content'])
                                else:
                                    new_node[k].append(transformed_child)
                        else:
                            new_node[k] = transform(v)
                    else:
                        new_node[k] = transform(v)
                return new_node
            elif isinstance(node, list):
                return [transform(child) for child in node]
            else:
                return node

        transformed = transform(adf_doc)

        # 첨부 링크가 전혀 포함되지 못한 경우, 문서 끝에 첨부 목록을 추가
        if isinstance(transformed, dict) and transformed.get('type') == 'doc':
            urls = [u for u in filename_to_url.values() if u]
            if urls:
                attachments_list = {
                    "type": "bulletList",
                    "content": [{
                        "type": "listItem",
                        "content": [{
                            "type": "paragraph",
                            "content": [{
                                "type": "text",
                                "text": name,
                                "marks": [{"type": "link", "attrs": {"href": url}}]
                            }]
                        }]
                    } for name, url in filename_to_url.items()]
                }
                transformed.setdefault('content', []).append({"type": "paragraph", "content": [{"type": "text", "text": "Attachments:"}]})
                transformed['content'].append(attachments_list)
        return transformed

    def clone_issue_with_media_upload(self, source_issue_key, project_key, summary=None, issue_type="Task", due_date=None, labels=None, link_type="Relates", models=None):
        """
        [KO] 원본 이슈의 설명/첨부/링크를 보존하며 새 이슈를 생성합니다.
        - 생성 시에는 텍스트-only ADF로 안전하게 생성하고, 이후 media 노드를 첨부 링크로 변환하여 설명을 업데이트합니다.
        [EN] Clone issue preserving description/attachments/link. Create safely, then transform ADF media to attachment links and update.
        """
        source = self.get_issue(source_issue_key)
        if not source:
            print(f"Failed to fetch source issue: {source_issue_key}")
            return None

        fields = source.get('fields', {})
        original_desc = fields.get('description')
        new_summary = summary or fields.get('summary', f"Cloned from {source_issue_key}")

        # 1) 안전 생성 (create_issue 내부에서 텍스트-only 처리 및 링크 생성 수행)
        new_issue_key = self.create_issue(
            project_key=project_key,
            summary=new_summary,
            issue_type=issue_type,
            description=None,
            due_date=due_date,
            labels=labels,
            linked_issue_key=source_issue_key,
            models = models
        )
        if not new_issue_key:
            return None

        # 2) 첨부 복사
        copied = self.copy_attachments(source_issue_key, new_issue_key)

        # 3) ADF를 첨부 링크로 변환 후 설명 업데이트
        if isinstance(original_desc, dict):
            transformed_adf = self._adf_replace_media_with_attachment_links(original_desc, copied)
            update_url = f"{self.base_url}/rest/api/3/issue/{new_issue_key}"
            update_payload = json.dumps({"fields": {"description": transformed_adf}})
            update_response = requests.put(update_url, headers=self.headers, auth=self.auth, data=update_payload)
            if not update_response.ok:
                print(f"Warning: Failed to update transformed description: {update_response.status_code}, {update_response.text}")

        return new_issue_key


if __name__ == "__main__":
    # 인자 파싱
    parser = argparse.ArgumentParser(description="Jira JQL Search CLI")
    parser.add_argument('-jql', '--jql', type=str, help="JQL query to execute (e.g., 'project = SI')")
    parser.add_argument("--env", type=str, default=".env", help="Path to .env file (default: .env)")
    args = parser.parse_args()

    # .env 파일 로드
    env_path = Path(args.env)
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

    # Jira 클라이언트 실행
    client = JiraClient(base_url, email, api_token)
    issues = client.search_issues_by_jql(args.jql)

    for issue in issues:
        key = issue.get("key")
        summary = issue.get("fields", {}).get("summary", "")
        print(f"- {key}: {summary}")
        
        #연결된 이슈 리스트 가져온다.
        linked = client.get_linked_issues(key)
        print('<<linked issue list :>>')
        for item in linked:
            print(f"{item['direction']} link ({item['type']}): {item['issue_key']} - {item['summary']}")