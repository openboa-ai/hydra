"""Wire page membership is distinct from a composed renderer view."""
from pathlib import Path
import json,runpy,unittest
from hydra_sdlc import projection as p

class ProjectionPageCountTests(unittest.TestCase):
    def test_returned_membership_matches_actual_project_records(self):
        emit=runpy.run_path(str(Path(__file__).parent/'fixtures/control-v3/emit_read_page_counts.py'))
        vectors=emit['vectors']()
        self.assertEqual(len(vectors),12)
        for case in vectors:
            with self.subTest(case=case['name']):
                value=p.read_json(case['wire'].encode())
                if case['accepted']:
                    self.assertEqual(json.loads(p.encode(value))['projects'],value['projects'])
                else:
                    with self.assertRaises(p.ProjectionError,msg=case['name']):p.encode(value)
