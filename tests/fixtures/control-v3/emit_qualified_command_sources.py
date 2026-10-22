from pathlib import Path
import json,sys
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(root),str(root/'tests')]
from test_qualified_command_sources import qualified_vectors
print(json.dumps(qualified_vectors()))
