"""Actual local producer bytes: no provider calls, facts or retry claims."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3];sys.path[:0]=[str(root),str(root/'tests')]
from test_projection_read import ReadFixture
from hydra_sdlc import projection as p
fixture=ReadFixture();frame=fixture.read(refresh=False,repository=sys.argv[2] if len(sys.argv)>2 else None)
assert fixture.calls==[]
frame['request_id']=sys.argv[1]
print(p.encode(frame).decode())
