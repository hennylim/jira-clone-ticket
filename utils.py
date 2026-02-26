import re
try:
    from googletrans import Translator  # type: ignore
    _translator = Translator()
except Exception:
    _translator = None

def contains_japanese(text):
    if not text:
        return False
    jp_pattern = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]")
    return bool(jp_pattern.search(text))

def translate_japanese_segments_to_korean(text):
    if not text or _translator is None:
        return text
    def _is_japanese_char(ch):
        return bool(re.match(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]", ch))
    segments = []
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
    summary = sanitize_double_quotes(summary)
    summary = f"Clone-{summary}({org_key})"
    return summary, description, org_key