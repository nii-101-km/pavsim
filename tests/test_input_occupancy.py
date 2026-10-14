import pathlib, subprocess, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class InputOccupancyTest(unittest.TestCase):
    def test_actual_drag_handlers(self):
        result=subprocess.run(['node',str(ROOT/'tests/test_input_occupancy.js')],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('INPUT OCCUPANCY TESTS PASSED',result.stdout)
