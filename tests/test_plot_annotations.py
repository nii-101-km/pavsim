import pathlib,subprocess,unittest
from xcos_mini.workspace_blocks import axis_range
from xcos_mini.core import BlockError,Library
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PlotAnnotationsTest(unittest.TestCase):
 def test_axis_ranges_and_renamed_metadata(self):
  self.assertIsNone(axis_range('','X'))
  self.assertEqual(axis_range(' -2: 5 ','X'),[-2,5])
  for text in ['1:1','5:0','nan:2','0:inf','0,5','a:b']:
   with self.subTest(text=text),self.assertRaises(BlockError):axis_range(text,'X')
  lib=Library(str(ROOT/'blocks'));block=lib.instantiate('graph_xyz')
  self.assertEqual(block.display_name,'XY с оценкой')
  self.assertEqual(block.input_labels,['x','y','J'])
  self.assertNotIn('z_mode',block.params)
  for name in ['graph_xy','graph_xyz']:
   b=lib.instantiate(name);b.params.update(x_range='0:5',y_range='-1:2');b.prepare(.1)
   b.params['x_range']='5:0'
   with self.assertRaises(BlockError):b.prepare(.1)
 def test_actual_renderer_labels_ranges_and_hover(self):
  result=subprocess.run(['node','tests/test_plot_annotations.js'],cwd=ROOT,capture_output=True,text=True,timeout=30)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  self.assertIn('PLOT ANNOTATION TESTS PASSED',result.stdout)
