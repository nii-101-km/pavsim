"""Catalog completeness plus behavioral production-editor EN/RU regressions.

DOM harnesses do not replace the separate real-browser acceptance check.
"""
import ast
import copy
import json
from pathlib import Path
import re
import subprocess
import unittest

from xcos_mini.core import Library, Engine
from xcos_mini.server import _build_model

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    source = (ROOT / 'xcos_mini/web/i18n-catalog.js').read_text()
    return json.loads(source.split(' = ', 1)[1].rstrip(';\n'))


def diagnostic_template(node):
    def parts(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return [n.value]
        if isinstance(n, ast.JoinedStr):
            return sum((parts(v) for v in n.values), [])
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return parts(n.left) + parts(n.right)
        return [None]
    output, index = '', 0
    for item in parts(node):
        if item is None:
            output += '{' + str(index) + '}'
            index += 1
        else:
            output += item
    return output


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = catalog()
        cls.lib = Library(str(ROOT / 'blocks'))
        cls.models = [json.loads(p.read_text()) for p in sorted((ROOT / 'examples').glob('*.json'))]
        # Exercise concrete labels interpolated into validation errors, too.
        from xcos_mini.optimization import finite
        concrete_errors = []
        for path in (ROOT / 'xcos_mini').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'finite' and len(node.args) > 1
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    try:
                        finite(float('nan'), node.args[1].value)
                    except Exception as error:
                        concrete_errors.append(str(error))
        cls.payload = dict(blocks=cls.lib.describe(), models=cls.models,
                           tree=[dict(name=k, type='category', blocks=v) for k, v in cls.lib.categories().items()],
                           diagnostics=[s for s, k in cls.translations['sources'].items() if k.startswith('error.')] + concrete_errors)

    def run_editor(self, scenario):
        proc = subprocess.run(['node', 'tests/test_i18n.js', scenario], cwd=ROOT,
                              input=json.dumps(self.payload), text=True, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('I18N ' + scenario + ' PASSED', proc.stdout)
        return proc.stdout

    def test_english_catalog_complete(self):
        for key, value in self.translations['en'].items():
            with self.subTest(key=key):
                self.assertTrue(value)
                self.assertIsNone(re.search('[а-яА-ЯёЁ]', value))
        for key in self.translations['sources'].values():
            self.assertIn(key, self.translations['en'])

    def test_russian_catalog_complete(self):
        self.assertEqual(set(self.translations['en']), set(self.translations['ru']))
        for key, value in self.translations['ru'].items():
            with self.subTest(key=key):
                self.assertTrue(value)
                placeholders = lambda s: sorted(re.findall(r'\{(\w+)\}', s))
                self.assertEqual(placeholders(value), placeholders(self.translations['en'][key]))

    def test_all_registered_metadata_localized(self):
        self.assertEqual(len(self.lib.names()), 61)
        for language in ('en', 'ru'):
            strings = self.translations[language]
            for block in self.lib.describe():
                for field in ('name', 'description'):
                    self.assertIn('block.' + block['name'] + '.' + field, strings)
                for key in block['parameters']:
                    self.assertIn('param.' + key, strings)
                    self.assertIn('hint.param.' + key, strings)
                for choices in block.get('parameter_choices', {}).values():
                    for choice in choices:
                        key = ('literal.' if choice['value'] in ('rk4', 'euler') else 'choice.') + choice['value']
                        self.assertIn(key, strings)
            for category in self.lib.categories():
                self.assertIn('category.' + category, strings)
        self.run_editor('metadata')

    def test_stock_diagnostic_coverage(self):
        paths = list((ROOT / 'xcos_mini').glob('*.py')) + list((ROOT / 'blocks').rglob('*.py'))
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                    source = diagnostic_template(node.exc.args[0])
                    if source != '{0}':
                        with self.subTest(file=path.name, source=source):
                            self.assertIn(source, self.translations['sources'])
        self.run_editor('errors')

    def test_first_launch_switch_and_persistence(self):
        self.run_editor('default')

    def test_english_fallback_and_unavailable_storage(self):
        self.run_editor('fallback')

    def test_model_results_and_editor_state_preserved_on_switch(self):
        self.run_editor('state')

    def test_unsaved_dialog_values_and_user_labels_preserved(self):
        self.run_editor('dialog')

    def test_dynamic_dialogs_refresh_and_status_retranslation(self):
        self.run_editor('dynamic')

    def test_boundary_protection_in_both_languages(self):
        self.run_editor('boundary')

    def test_en_ru_save_load_en_models_and_numerical_equivalence(self):
        output = self.run_editor('roundtrip')
        roundtripped = json.loads(next(line[7:] for line in output.splitlines() if line.startswith('MODELS:')))
        self.assertEqual(len(roundtripped), 5)
        from xcos_mini.experiments import execute_workspace
        build = lambda model: _build_model(self.lib, model)
        for original, saved in zip(self.models, roundtripped):
            with self.subTest(blocks=len(original['blocks'])):
                # Coordinates/default presentation are normalized by the existing
                # serializer; all computational data and connections must survive.
                for before, after in zip(original['blocks'], saved['blocks']):
                    self.assertEqual(before['id'], after['id'])
                    self.assertEqual(before['type'], after['type'])
                    self.assertEqual(before.get('params', {}), after['params'])
                reference = execute_workspace(copy.deepcopy(original), build, 1, .02, 'rk4')
                actual = execute_workspace(copy.deepcopy(saved), build, 1, .02, 'rk4')
                self.assertEqual(reference, actual)

    def test_plot_renderer_language_preserves_packet_and_points(self):
        proc = subprocess.run(['node', 'tests/test_plot_annotations.js'], cwd=ROOT,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('PLOT LANGUAGE TESTS PASSED', proc.stdout)
