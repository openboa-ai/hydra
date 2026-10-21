"""Literal derived-fact oracles; current encoder emits all positive cases."""
from pathlib import Path
import copy,json,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from hydra_sdlc import projection as p
FOLDER=Path(__file__).resolve().parent

def cases():
    base=json.loads((FOLDER/'inputs.json').read_text())['frame']
    commands=json.loads((FOLDER/'receipt-states.json').read_text())['commands']
    for n,row in enumerate(json.loads((FOLDER/'derived-facts.json').read_text())['cases']):
        frame=copy.deepcopy(base)
        admission=next(o for o in frame['observations'] if o['resource']['kind']=='admission')
        if row['kind']=='admission':
            mode=row['global_mode'];overrides={'example/beta':'running'}
            if row['override'] is not None:overrides['example/alpha']=row['override']
            admission['value'].update(global_mode=mode,project_overrides=overrides,
                                      gate_reason=None if mode=='running' else 'host_'+mode)
            effective={'running':'allowed','paused':'paused','stopped':'stopped'}
            alpha=effective[row['override'] or 'running'] if mode=='running' else mode
            beta='allowed' if mode=='running' else mode
            frame['projects'][0]['admission']['value']=alpha
            frame['projects'][1]['admission']['value']=beta
            frame['work'][0]['admission']['value']=alpha
            target=frame['projects'][0] if row['target']=='project' else frame['work'][0]
            target['admission']['value']=row['value']
        elif row['kind']=='admission-context':
            name=row['name'];target=frame['projects'][0];work=frame['work'][0]
            if name=='foreign-store':admission['resource']['id']='f'*64
            elif name=='missing-store-binding':frame['runtime'].update(control_binding_digest=None,identity_reason='control_binding_unavailable')
            elif name=='conflicting-snapshots':
                other=copy.deepcopy(admission);other['key']='hydra:second:admission'
                other['revision']={'kind':'monotonic','value':'8'}
                other['value'].update(revision=8,global_mode='stopped',gate_reason='host_stopped')
                frame['observations'].append(other)
                for item in (target,work):item['admission']['evidence'].append(p.evidence_of(other))
            else:
                admission['value'].update(global_mode='running',project_overrides={'example/alpha':'paused','example/beta':'running'},gate_reason=None)
                frame['projects'][1]['admission']['value']='allowed'
                if name=='missing-repository-context':
                    target['repository_ref']['id']='303';target['work_refs']=[];target['admission']['value']='allowed';frame['work']=[]
                else:
                    repo=next(o for o in frame['observations'] if o['resource']['kind']=='repository' and o['resource']['id']=='101')
                    repo['key']='github:repository-request:example/alpha';repo['coverage']['scope']='repository-address:example/alpha'
                    repo['value']['full_name']='example/renamed'
                    target['source_refs'].append({'source':'github','kind':'repository','id':'requested:example/alpha'})
                    if name=='conflicting-aliases':
                        alias=copy.deepcopy(repo);alias['key']='github:repository-request:example/other';alias['coverage']['scope']='repository-address:example/other'
                        frame['observations'].append(alias)
                        target['source_refs'].append({'source':'github','kind':'repository','id':'requested:example/other'})
        elif row['kind']=='repository':
            observed=next(o for o in frame['observations'] if o['resource']['kind']=='repository' and o['resource']['id']=='101')
            observed['resource']['id']=row['identifier'];observed['value']['numeric_id']=row['number']
            observed['availability']=row['availability']
        elif row['kind']=='decision':
            observed=next(o for o in frame['observations'] if o['resource']['kind']==row['source_kind'])
            frame['work'][0]['decision'][row['axis']]=p.known(row['value'],[observed])
            if row['value']=='none':
                for axis in ('answer','acceptance','application'):frame['work'][0]['decision'][axis]=p.unknown('not_applicable')
            if row.get('capability_claim'):
                frame['capabilities']=[{'source':'codex','operation':'native_read','state':'available','actor':'native_actor',
                    'qualification_ref':'fixture:qualification','reason':None}]
        elif row['kind']=='unknown-decisions':
            observed=next(o for o in frame['observations'] if o['resource']['kind']=='issue')
            frame['work'][0]['decision']={axis:p.unknown('decision_provenance_unverified',[observed])
                for axis in ('question','answer','acceptance','application')}
        reply=copy.deepcopy(next(c['reply'] for c in commands if c['name']=='admission'))
        reply['observations']=frame['observations']
        reply['request'].update(outcome='rejected',reason='fixture_source_check',receipt=None,effect_refs=[],observed_refs=[],required_next='refresh')
        yield {'name':str(n)+'-'+row['kind'],'frame':frame,'reply':reply,
               'accepted_projection':row['accepted'],'accepted_standard':row['accepted'] if row['kind']=='repository' else True}

def vectors():
    output=[]
    for row in cases():
        for profile,key in [('projection','frame'),('standard','reply')]:
            accepted=row['accepted_'+profile];value=row[key]
            if accepted:
                wire=p.encode(value).decode() if profile=='projection' else json.dumps(p.standard_reply(value),separators=(',',':'))
            else:wire=json.dumps(value,separators=(',',':'))
            output.append({'name':row['name'],'profile':profile,'accepted':accepted,'wire':wire})
    return output

if __name__=='__main__':print(json.dumps(vectors(),separators=(',',':')))
