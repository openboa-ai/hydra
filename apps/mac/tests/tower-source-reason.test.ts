import assert from 'node:assert/strict';
import test from 'node:test';
import {appFixture,noMutations} from './tower-fixture.ts';
test('displayed source failure retains its cause instead of becoming a TTL expiry',async()=>{
 const app=await appFixture();
 try{await app.click('Inspect example/alpha');await app.click('Inspect work #7 in example/alpha');
  app.api.fail=true;await app.click('Refresh workflow sources');
  const source=app.lifecycle()?.querySelector('.tower-sources')?.textContent??'';
  assert.match(source,/Read unavailable/,'A fresh attempted source failure is distinct from elapsed TTL');
  assert.doesNotMatch(source,/Ttl expired/);noMutations(app.calls);
 }finally{app.close();}
});
