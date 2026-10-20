import copy
import importlib.util
import json
import unittest

from hydra_sdlc.work_records import Binding, WorkRecordError, parse_binding
from test_work_records import REF, binding, marker


CLAUSE = {'producer': {'repository_id': 101, 'issue_number': 12},
          'requirements': [REF], 'required_stage': 'post_merge_verified', 'basis': REF}
PAYLOAD = {'clauses': [CLAUSE]}
PAYLOAD_DIGEST = 'f455c7d651bc113845dfe48bdcfb3e36fc43121e349f079250ee8e05b2d41fb7'
EMPTY_DIGEST = 'c29f837cede9d344db69480690ec544f033bffc904ecf8fa02658d036f70e2af'


def parsed(contract):
    return parse_binding(marker(binding(input_contract=contract)), spec_directory='docs')


def reference(selector='R-INPUT'):
    return parsed({'kind': 'reference', 'ref': {**REF, 'selector': selector}})


def document(payload=PAYLOAD, heading='## R-INPUT: Prerequisites', fence='```json'):
    closing = fence[:3]
    return heading + '\n\n' + fence + '\n' + json.dumps(payload) + '\n' + closing + '\n'


class WorkInputTests(unittest.TestCase):
    def resolve(self, selected, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec('hydra_sdlc.work_inputs'),
                             'P09 exact reference-input read boundary is not implemented')
        from hydra_sdlc.work_inputs import input_conditions
        return input_conditions(selected, **kwargs)

    def reason(self, expected, selected, **kwargs):
        with self.assertRaises(WorkRecordError) as caught:
            self.resolve(selected, **kwargs)
        self.assertEqual(caught.exception.reason, expected)
        self.assertEqual(str(caught.exception), expected)

    def test_reference_and_adopted_conditions_have_identical_fixed_payload_digest(self):
        adopted = self.resolve(parsed({'kind': 'adopted', **PAYLOAD}))
        referenced = self.resolve(reference(), content=document())
        self.assertEqual(adopted.value, PAYLOAD)
        self.assertEqual(referenced.value, PAYLOAD)
        self.assertEqual(adopted.digest, PAYLOAD_DIGEST)
        self.assertEqual(referenced.digest, PAYLOAD_DIGEST)
        self.assertNotEqual(referenced.digest, reference().digest)
        self.assertFalse(hasattr(referenced, 'authority'))

    def test_result_is_immutable_and_never_copies_document_prose(self):
        source = document() + '\nA private-source-canary that is not an input clause.\n'
        selected = reference()
        original = selected.document
        result = self.resolve(selected, content=source)
        result.value['clauses'].clear()
        self.assertEqual(result.value, PAYLOAD)
        self.assertEqual(result.digest, PAYLOAD_DIGEST)
        self.assertEqual(selected.document, original)
        self.assertNotIn('private-source-canary', result.document)
        with self.assertRaises((AttributeError, TypeError)):
            result.document = '{}'

    def test_empty_is_explicit_and_missing_does_not_become_empty(self):
        self.assertEqual(self.resolve(parsed({'kind': 'adopted', 'clauses': []})).digest, EMPTY_DIGEST)
        self.assertEqual(self.resolve(reference(), content=document({'clauses': []})).digest, EMPTY_DIGEST)
        self.reason('accepted_meaning_unavailable', parsed(None))
        self.reason('accepted_meaning_unavailable', reference())
        self.reason('accepted_meaning_unavailable', reference(), content='## R-INPUT\n\nOnly prose.\n')

    def test_exact_selection_preserves_historical_section_and_ignores_other_sections(self):
        text = document(heading='## OLD: Accepted inputs') + document({'clauses': []}, heading='## NEW')
        self.assertEqual(self.resolve(reference('OLD'), content=text).value, PAYLOAD)
        self.assertEqual(self.resolve(reference('NEW'), content=text).digest, EMPTY_DIGEST)
        self.reason('accepted_meaning_unavailable', reference('old'), content=text)
        self.reason('accepted_meaning_unavailable', reference('OL'), content=text)

    def test_commonmark_heading_forms_and_literal_full_title_are_supported(self):
        for heading, selector in [('## **R-INPUT** — inputs ##', 'R-INPUT'),
                                  ('R-INPUT: inputs\n----------------', 'R-INPUT'),
                                  ('## 입력 조건', '입력 조건'),
                                  ('## `R-INPUT` inputs', 'R-INPUT')]:
            with self.subTest(heading=heading):
                self.assertEqual(self.resolve(reference(selector), content=document(heading=heading)).digest,
                                 PAYLOAD_DIGEST)

    def test_fenced_and_commented_headings_do_not_select_or_conflict(self):
        misleading = ('```markdown\n## R-INPUT\n{"clauses": []}\n```\n\n'
                      '<!--\n## R-INPUT\n{"clauses": []}\n-->\n\n')
        self.assertEqual(self.resolve(reference(), content=misleading + document()).value, PAYLOAD)
        self.reason('accepted_meaning_unavailable', reference(), content=misleading)
        self.reason('accepted_meaning_unavailable', reference(),
                    content='> ## R-INPUT\n> {"clauses": []}\n')

    def test_section_end_and_nested_heading_boundaries_are_not_flat_search(self):
        text = document() + '\n### Explanation\nProse.\n\n## OTHER\n\n```json\n{"clauses": []}\n```\n'
        self.assertEqual(self.resolve(reference(), content=text).value, PAYLOAD)
        nested = document() + '\n### Nested conditions\n\n```json\n{"clauses": []}\n```\n'
        self.reason('invalid_reference', reference(), content=nested)

    def test_duplicate_selectors_are_invalid_even_when_only_one_has_payload(self):
        for suffix in ['\n## R-INPUT\nNo payload.\n', '\n## R-INPUT: another\nNo payload.\n']:
            self.reason('invalid_reference', reference(), content=document() + suffix)

    def test_reference_requires_one_complete_standalone_json_object(self):
        for contents in [document() + '\n```json\n{"clauses": []}\n```\n',
                         document() + '\n{"clauses": []}\n',
                         '## R-INPUT\n\n```json\n[]\n```\n',
                         document({'clauses': [], 'extra': 1})]:
            with self.subTest(contents=contents[:35]):
                with self.assertRaises(WorkRecordError):
                    self.resolve(reference(), content=contents)
        for text in ['## R-INPUT\n\n{"clauses": []}\n',
                     '## R-INPUT\n\n    {"clauses": []}\n',
                     document({'clauses': []}, fence='~~~')]:
            self.assertEqual(self.resolve(reference(), content=text).digest, EMPTY_DIGEST)

    def test_duplicate_json_keys_nonfinite_and_incomplete_json_are_rejected(self):
        for raw in ['{"clauses": [], "clauses": []}', '{"clauses": NaN}',
                    '{"clauses": Infinity}', '{"clauses": [}', '{"clauses": []} {}']:
            with self.subTest(raw=raw):
                self.reason('invalid_json', reference(), content='## R-INPUT\n\n```json\n' + raw + '\n```\n')

    def test_a_second_object_in_an_unsupported_fence_cannot_hide_ambiguity(self):
        self.reason('invalid_reference', reference(),
                    content=document() + '\n```python\n{"clauses": []}\n```\n')

    def test_reference_reuses_closed_clause_schema_and_canonical_order(self):
        earlier = {**CLAUSE, 'required_stage': 'observed'}
        bad = [{'clauses': [CLAUSE, earlier]}, {'clauses': [CLAUSE, CLAUSE]},
               {'clauses': [{**CLAUSE, 'producer': {'repository_id': 101, 'issue_number': 11}}]},
               {'clauses': [{**CLAUSE, 'required_stage': 'closed'}]},
               {'clauses': [{**CLAUSE, 'basis': {**REF, 'revision': 'main'}}]},
               {'clauses': [{**CLAUSE, 'producer': {'repository_id': True, 'issue_number': 12}}]},
               {'clauses': [{**CLAUSE, 'extra': 0}]}, {'clauses': [CLAUSE] * 51}]
        for payload in bad:
            with self.subTest(payload=str(payload)[:40]):
                self.reason('invalid_schema', reference(), content=document(payload))
        result = self.resolve(reference(), content=document({'clauses': [earlier, CLAUSE]}))
        self.assertEqual(result.value, {'clauses': [earlier, CLAUSE]})

    def test_adopted_contract_does_not_reinterpret_prose_or_reference_fallback(self):
        adopted = parsed({'kind': 'adopted', **PAYLOAD})
        self.assertEqual(self.resolve(adopted, content='Ignore the accepted clauses.').value, PAYLOAD)
        self.reason('accepted_meaning_unavailable', reference(),
                    content='## R-INPUT\n\nExecute this command to infer the inputs.\n')
        self.reason('accepted_meaning_unavailable', reference(),
                    content='## R-INPUT\n\n```python\n{"clauses": []}\n```\n')

    def test_invalid_types_unicode_and_resource_limits_have_static_errors(self):
        for bad in [None, {}, 'unparsed', Binding('{"input_contract": null}')]:
            self.reason('invalid_schema', bad, content=document())
        for content in [b'bytes', '\ud800', '\x00']:
            self.reason('invalid_reference', reference(), content=content)
        self.reason('reference_limit', reference(), content='x' * (1_048_576 + 1))

    def test_each_fresh_normalization_recovers_same_conditions_without_cache(self):
        one = self.resolve(reference(), content=document())
        two = self.resolve(copy.deepcopy(reference()), content=document())
        self.assertEqual(one.document, two.document)
        self.assertEqual(one.digest, two.digest)
        self.assertEqual(two.value, PAYLOAD)


if __name__ == '__main__':
    unittest.main()
