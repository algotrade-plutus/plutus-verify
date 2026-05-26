from plutus_verify.util.llm_parsing import strip_markdown_fences


def test_plain_text_unchanged():
    assert strip_markdown_fences('{"a": 1}') == '{"a": 1}'


def test_plain_text_trims_whitespace():
    assert strip_markdown_fences('  {"a": 1}  \n') == '{"a": 1}'


def test_strips_bare_fences():
    assert strip_markdown_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strips_json_fence_label():
    assert strip_markdown_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strips_uppercase_json_label():
    assert strip_markdown_fences('```JSON\n{"a": 1}\n```') == '{"a": 1}'


def test_leading_whitespace_around_fence():
    assert strip_markdown_fences('  \n```json\n{"a": 1}\n```\n  ') == '{"a": 1}'


def test_multiline_body_preserved():
    body = '{\n  "a": 1,\n  "b": 2\n}'
    assert strip_markdown_fences(f'```json\n{body}\n```') == body


def test_inner_backticks_preserved():
    body = 'use `foo` in code'
    assert strip_markdown_fences(f'```\n{body}\n```') == body
