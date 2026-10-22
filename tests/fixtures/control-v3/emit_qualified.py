"""Literal claim oracles with actual producer bytes for every positive profile."""
from pathlib import Path
import copy,importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from hydra_sdlc import projection as p
FOLDER=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('wire_fixture',FOLDER/'emit_wire.py')
wire=importlib.util.module_from_spec(spec);spec.loader.exec_module(wire)
OWNERS={'repository':'github','issue':'github','progress':'github','pull_request':'github','check':'github',
 'review':'github','native_task_metadata':'codex','native_history_page':'codex','native_task':'codex',
 'native_schedule':'codex','resource':'resource_provider','admission':'hydra','ownership':'hydra'}
def observed(frame,kind):
    found=next((o for o in frame['observations'] if o['resource']['kind']==kind),None)
    if found is not None:return found
    issue={'source':'github','kind':'issue','id':'101:7'}
    task={'source':'codex','kind':'native_task','id':'00000000-0000-4000-8000-000000000003'}
    schedule={'source':'codex','kind':'native_schedule','id':'fixture-schedule'}
    values={
      'progress':{'issue_ref':issue,'attempt_id':None,'native_step':None,'head':None,'contract_revision':None,
        'expected_head':None,'expected_base':None,'published_head':None,'branch':None,'phase':'complete',
        'wait_reason':None,'next_action':'continue','pending_action':None,'cleanup_state':'complete','pr_ref':None,'completion_refs':None},
      'pull_request':{'number':7,'url':'https://github.com/example/alpha/pull/7','state':'closed',
        'head':'a'*40,'base':'b'*40,'merge_commit':'c'*40,'required_check_refs':[],'review_refs':[]},
      'check':{'producer':None,'name':'fixture','head':'a'*40,'status':'completed','conclusion':'success','url':None},
      'review':{'producer':None,'head':'a'*40,'state':'approved','unresolved_count':0,'url':None},
      'native_history_page':{'task_ref':task,'page':{'order':'newest_first','limit':1,'has_more':False},'turns':[]},
      'native_task':{'task_ref':task,'assignment_ref':None,'execution':{'state':'ended','active_count':0},
        'question_ref':None,'schedule_refs':[],'open_ref':None},
      'native_schedule':{'schedule_ref':schedule,'task_ref':None,'status':'paused','next_wake_at':None,'open_ref':None},
      'resource':{'resource_ref':{'source':'resource_provider','kind':'workspace','id':'fixture-owned'},
        'owner_ref':issue,'activity':'idle','preservation':'preserved','retirement':'retired','open_ref':None},
      'ownership':{'state':'free','scope_digest':None,'step_nonce':None}}
    row=copy.deepcopy(frame['observations'][0]);row.update(key='fixture:qualified:'+kind,
      resource={'source':OWNERS[kind],'kind':kind,'id':task['id'] if kind=='native_task' else 'fixture-'+kind},
      revision=None,value=values[kind]);row['coverage']['scope']='fixture:'+kind
    if kind=='native_history_page':
        row['coverage'].update(state='partial',returned_count=0,total_count=None,next_cursor=None,reason='history_scope_unverified')
    frame['observations'].append(row);return row
def diagnostic(frame):
    reply=wire.standard(frame)
    reply['request'].update(outcome='rejected',reason='fixture_source_check',receipt=None,
                            effect_refs=[],observed_refs=[],required_next='refresh')
    reply['observations']=copy.deepcopy(frame['observations']);return reply
def cases():
    base=json.loads((FOLDER/'inputs.json').read_text())['frame']
    for n,row in enumerate(json.loads((FOLDER/'qualified-facts.json').read_text())['cases']):
        frame=copy.deepcopy(base);work=frame['work'][0];issue=next(o for o in frame['observations'] if o['resource']['kind']=='issue')
        family=row['family']
        if family in ('unmapped','project_execution','unknown'):
            source=observed(frame,row['source_kind'])
            if family=='unmapped':
                value=copy.deepcopy(row['value'])
                if row['axis']=='next_action':value['evidence']=[p.evidence_of(source)]
                work[row['axis']]={'value':value,'evidence':[p.evidence_of(source)],'reason':None}
            elif family=='project_execution':frame['projects'][0]['execution']={'value':copy.deepcopy(row['value']),'evidence':[p.evidence_of(source)],'reason':None}
            else:
                for axis in ('stage','execution','wait','delivery','result','cleanup','next_action'):
                    work[axis]=p.unknown('qualified_mapping_unavailable',[source])
                frame['projects'][0]['execution']=p.unknown('qualified_mapping_unavailable',[source])
        elif family=='readiness':
            value=work['readiness']['value'];name=row['name']
            if name=='other_source':value['source_ref']['id']='101:8'
            elif name=='other_revision':value['source_revision']={'kind':'opaque','value':'different'}
            elif name=='other_evidence':
                other=copy.deepcopy(issue);other['key']='github:101:issue:8';other['resource']['id']='101:8';other['value']['number']=8
                frame['observations'].append(other);work['readiness']['evidence']=[p.evidence_of(other)]
            elif name=='foreign_evidence_kind':work['readiness']['evidence']=[p.evidence_of(observed(frame,'ownership'))]
            elif name=='other_work':work['issue_ref']['id']='101:8';frame['projects'][0]['work_refs'][0]['id']='101:8'
            elif name=='matching_revision':
                issue['revision']={'kind':'opaque','value':'current-issue-revision'}
                value['source_revision']=copy.deepcopy(issue['revision']);work['readiness']['evidence']=[p.evidence_of(issue)]
                work['evidence_refs']=[p.evidence_of(issue)]
            elif name=='mixed_evidence':work['readiness']['evidence'].append(p.evidence_of(observed(frame,'ownership')))
            elif name=='actionable':value['disposition']='actionable'
            elif name=='confirmed_authority':value['authority']='confirmed'
            elif name=='interpretation':value['interpretation_ref']={'source':'hydra','kind':'interpretation','id':'fixture'}
            elif name=='binding':value['binding_ref']={'source':'hydra','kind':'binding','id':'fixture'}
            elif name=='extracted':value['extracted']['purpose_excerpt']='Unsupported interpreted purpose'
        elif family=='relation':
            name=row['name'];child=copy.deepcopy(issue['resource']);parent={'source':'github','kind':'issue','id':'101:1'}
            issue['value']['parent_refs']=[{'repository_id':101,'issue_number':1}]
            relation={'from':child,'to':parent,'kind':'parent','evidence':[p.evidence_of(issue)]}
            if name=='matching_goal_ref':issue['value']['parent_refs'][0]['source_digest']='c'*64
            elif name=='cross_repository':issue['value']['parent_refs'][0]={'repository_id':102,'issue_number':4};relation['to']['id']='102:4'
            elif name=='mixed_evidence':relation['evidence'].append(p.evidence_of(observed(frame,'ownership')))
            elif name=='missing_payload':issue['value']['parent_refs']=None
            elif name=='empty_payload':issue['value']['parent_refs']=[]
            elif name=='other_parent':relation['to']['id']='101:2'
            elif name=='other_child':relation['from']['id']='101:8'
            elif name=='reversed':relation['from'],relation['to']=relation['to'],relation['from']
            elif name=='foreign_evidence':relation['evidence']=[p.evidence_of(observed(frame,'ownership'))]
            elif name=='non_issue_endpoint':relation['to']={'source':'github','kind':'repository','id':'101'}
            elif name in ('depends_on','implements','verifies','delivers'):relation['kind']=name
            frame['relations']=[relation]
        elif family=='project_refs':
            name=row['name'];refs=frame['projects'][0]['work_refs']
            if name=='foreign_repository':refs[0]['id']='102:7'
            elif name=='foreign_source':refs[0]['source']='codex'
            elif name=='not_issue':refs[0]={'source':'github','kind':'repository','id':'101'}
            elif name=='noncanonical_repository':refs[0]['id']='0101:7'
            elif name=='noncanonical_number':refs[0]['id']='101:07'
            elif name=='duplicate':refs.append(copy.deepcopy(refs[0]))
            elif name.startswith('unresolved_'):
                frame['projects'][0]['repository_ref']['id']='requested:example/alpha'
                if name=='unresolved_empty':
                    project=frame['projects'][0];project['work_refs']=[]
                    project['coverage'].update(returned_count=0,total_count=0 if project['coverage']['state']=='complete' else None)
                    frame['work']=[work for work in frame['work'] if not work['issue_ref']['id'].startswith('101:')]
        if family=='receipt':
            reply=wire.standard(frame);name=row['name']
            if name=='foreign_store':reply['observations'][0]['resource']['id']='f'*64
            elif name=='legacy_host':reply['observations'][0]['resource']['id']='host'
            elif name=='missing_binding':reply['runtime']['control_binding_digest']=None
            frame.update(runtime=copy.deepcopy(reply['runtime']),observations=copy.deepcopy(reply['observations']),
                         projects=[],work=[],relations=[],request=copy.deepcopy(reply['request']))
            frame['page']={'state':'complete','scope':'fixture;empty','returned_count':0,'total_count':0,'next_cursor':None,'reason':None}
        else:reply=diagnostic(frame)
        yield {'name':str(n)+'-'+family+'-'+row.get('name',row.get('axis','unknown')),'family':family,
               'frame':frame,'reply':reply,'accepted_projection':row['accepted_projection'],'accepted_standard':row['accepted_standard']}
def vectors():
    result=[]
    for row in cases():
        for profile,key in [('projection','frame'),('standard','reply')]:
            accepted=row['accepted_'+profile];value=row[key]
            data=p.encode(value).decode() if accepted and profile=='projection' else (
                json.dumps(p.standard_reply(value),separators=(',',':')) if accepted else json.dumps(value,separators=(',',':')))
            result.append({'name':row['name'],'family':row['family'],'profile':profile,'accepted':accepted,'wire':data})
    return result
if __name__=='__main__':print(json.dumps(vectors(),separators=(',',':')))
