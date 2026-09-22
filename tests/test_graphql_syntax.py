"""Parse real operation strings so fake transports cannot hide broken GraphQL."""
import ast
import importlib
from pathlib import Path
import unittest

from graphql import parse


class GraphQLSyntaxTests(unittest.TestCase):
    def test_static_operations_parse(self):
        root = Path(__file__).resolve().parents[1]
        checked = 0
        for name in ('workspace', 'authoring', 'review_workspace', 'workspace_actions', 'reader_client'):
            module = importlib.import_module(name)
            filename = root / (name + '.py')
            for call in ast.walk(ast.parse(filename.read_text())):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == 'graph' and call.args):
                    continue
                expression = call.args[0]
                if isinstance(expression, ast.JoinedStr):
                    continue  # Runtime-selected mutations are exercised by action tests.
                query = eval(compile(ast.Expression(expression), str(filename), 'eval'), vars(module))
                with self.subTest(module=name, line=call.lineno):
                    parse(query)
                checked += 1
        self.assertGreaterEqual(checked, 15)
