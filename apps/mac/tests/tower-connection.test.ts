/** P17 producer -> P12 strict reducer -> actual P16 app-entry integration. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { appFixture, noMutations } from './tower-fixture.ts';

const script=fileURLToPath(new URL('../../../tests/fixtures/control-v3/emit_connection_guards.py',import.meta.url));
const result=spawnSync('python3',['-I',script],{encoding:'utf8',timeout:60_000,maxBuffer:4_194_304});
assert.equal(result.status,0,'The actual configured connection producer must run');
const rows=JSON.parse(result.stdout) as {name:string;accepted:boolean;wire:string}[];
assert.equal(rows.length,6);
const expected:Record<string,[string,string]>={
  'disconnect-keeps-stored-running-but-blocks-project':['Unconfirmed','Allowed'],
  'unprepared-running-override-is-not-permission':['Unconfirmed','Allowed'],
  'connected-current-projects-can-progress':['Allowed','Allowed'],
  'host-pause-remains-the-known-limiting-mode':['Paused','Paused'],
};

for(const row of rows) {
  test('actual connection source reaches the control tower: '+row.name,async()=>{
    const app=await appFixture(JSON.parse(row.wire));
    try {
      assert.ok(app.calls.some(c=>c.method==='projection_status'),'Use the actual read entry');
      if(!row.accepted) {
        assert.match(app.lifecycle()?.textContent??'',/sources are unconfirmed/i);
        assert.equal(app.lifecycle()?.querySelector('.tower-project'),null,
          'A forged allowed claim cannot create a displayed project');
      } else {
        assert.ok(Object.hasOwn(expected,row.name),'Each accepted source needs an independent expected result');
        const values=expected[row.name]!;
        const admission=()=>[...app.lifecycle()!.querySelectorAll('.tower-detail .tower-fact')]
          .find(field=>field.querySelector('dt')?.textContent==='Admission')?.querySelector('dd')?.textContent;
        for(const [index,repository,issue] of [[0,'example/alpha',7],[1,'example/beta',8]] as const) {
          await app.click('Inspect '+repository);
          assert.equal(admission(),values[index],repository+' project admission');
          await app.click(`Inspect work #${issue} in ${repository}`);
          assert.equal(admission(),values[index],repository+' work admission');
          assert.doesNotMatch(app.lifecycle()?.textContent??'',/0 active|all work complete|execution ended/i);
        }
        if(values[0]==='Unconfirmed') {
          await app.click('Inspect example/alpha');
          assert.match(app.lifecycle()?.textContent??'',/Project (disconnect requested|connection unprepared)/,
            'Retain the actual connection reason beside unconfirmed permission');
        }
      }
      noMutations(app.calls);
    } finally { app.close(); }
  });
}
