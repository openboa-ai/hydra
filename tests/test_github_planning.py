"""Optional priority semantics use source IDs, complete scopes and no writes."""
import copy,json,unittest
from unittest.mock import patch
from hydra_sdlc.github import GitHub,GitHubError
from hydra_sdlc.project import ProjectError

P='PVT_fixture_alpha';F='PVTSSF_fixture_priority';I='PVTI_fixture_issue';O='option-critical'
SOURCE={'repository_id':101,'issue_number':7}
POLICY={'source':'github_project','project_id':P,'priority_field_id':F,'option_priorities':{O:42,'option-low':-5}}
CANARY='SYNTHETIC_UNTRUSTED_PRIVATE_CANARY'
def repo():return {'databaseId':101,'nameWithOwner':'example/alpha','isPrivate':False,'viewerPermission':'READ'}
def issue():return {'__typename':'Issue','id':'I_fixture_7','number':7,'repository':repo()}
def item(identifier=I,project=P):return {'__typename':'ProjectV2Item','id':identifier,'type':'ISSUE','project':{'id':project},'content':issue()}
def field():return {'__typename':'ProjectV2SingleSelectField','id':F,'project':{'id':P},'dataType':'SINGLE_SELECT','options':[{'id':O},{'id':'option-low'}]}
def value(option=O,identifier=F,typename='ProjectV2ItemFieldSingleSelectValue'):
    result={'__typename':typename,'field':{'id':identifier,'dataType':'SINGLE_SELECT' if typename=='ProjectV2ItemFieldSingleSelectValue' else 'TEXT','project':{'id':P}}}
    if typename=='ProjectV2ItemFieldSingleSelectValue':result['optionId']=option
    return result
def connection(nodes,total=None,more=False,cursor=None):
    return {'totalCount':len(nodes) if total is None else total,'nodes':nodes,'pageInfo':{'hasNextPage':more,'endCursor':cursor}}
def frame():return {'data':{'repository':{**repo(),'issue':{'id':'I_fixture_7','number':7}},
    'project':{'__typename':'ProjectV2','id':P},'priorityField':field()}}
def membership(nodes=None,**kwargs):
    raw=frame();raw['data']['repository']['issue']['projectItems']=connection([item()] if nodes is None else nodes,**kwargs);return raw
def values(nodes=None,**kwargs):
    raw=frame();raw['data']['item']=item();raw['data']['item']['fieldValues']=connection([value()] if nodes is None else nodes,**kwargs);return raw

class Fixture:
    def __init__(self,members=None,fields=None):
        self.members=members or [membership()];self.fields=fields or [values()];self.calls=[];self.rotate=False;self.mutate=None
        self.client=GitHub(transport=self.transport)
    def transport(self,method,path,payload):
        assert method=='POST' and path=='/graphql' and type(payload) is dict
        query=payload['query'];assert query.startswith('query ') and 'mutation' not in query.lower()
        kind='members' if 'HydraNativePlanningMembership' in query else 'fields'
        assert kind=='members' or 'HydraNativePlanningValues' in query
        self.calls.append((kind,copy.deepcopy(payload)))
        if self.rotate:self.client._authenticated_fingerprint=b'a' if len(self.calls)==1 else b'b'
        if self.mutate:self.mutate()
        rows=self.members if kind=='members' else self.fields
        index=sum(k==kind for k,_ in self.calls)-1
        if index>=len(rows):raise GitHubError('Fixture page unavailable')
        if isinstance(rows[index],Exception):raise rows[index]
        return copy.deepcopy(rows[index])
    def read(self,policy=None,source=None):
        return self.client.native_planning_read('example/alpha',SOURCE if source is None else source,POLICY if policy is None else policy).value

class PlanningReadTests(unittest.TestCase):
    def known(self,f,priority):
        result=f.read();self.assertEqual(result['coverage'],'complete');self.assertEqual(result['priority'],priority)
        self.assertIsNone(result['reason']);self.assertEqual(result['source'],SOURCE);return result
    def unknown(self,f):
        result=f.read();self.assertNotEqual(result['coverage'],'complete');self.assertIsNone(result['priority'])
        self.assertIsNotNone(result['reason']);return result
    def test_option_ids_determine_priority_without_a_display_name(self):
        f=Fixture();self.known(f,42);self.assertEqual([k for k,_ in f.calls],['members','fields'])
        self.assertEqual(f.calls[0][1]['variables']['project'],P);self.assertEqual(f.calls[0][1]['variables']['field'],F)
        self.assertIn('includeArchived:true',f.calls[0][1]['query'].replace(' ',''))
        self.assertNotIn('fieldValueByName',f.calls[1][1]['query'])
    def test_explicit_null_and_complete_unset_field_use_zero(self):
        for nodes in ([value(None)],[],[value(identifier='field-other',typename='ProjectV2ItemFieldTextValue')]):
            with self.subTest(nodes=nodes):self.known(Fixture(fields=[values(nodes)]),0)
    def test_negative_policy_priority_is_preserved(self):self.known(Fixture(fields=[values([value('option-low')])]),-5)
    def test_display_name_changes_preserve_id_mapping(self):
        raw=values();raw['data']['priorityField']['name']='Renamed priority';raw['data']['priorityField']['options'][0]['name']='Low'
        self.known(Fixture(fields=[raw]),42)
    def test_missing_or_duplicate_selected_project_item_is_unavailable(self):
        for nodes in ([],[item(project='PVT_other')],[item(),item('PVTI_duplicate')]):
            with self.subTest(nodes=nodes):self.unknown(Fixture(members=[membership(nodes)]))
    def test_redacted_null_or_foreign_item_cannot_supply_absence_or_priority(self):
        for change in ('redacted','null','foreign_issue','foreign_repository'):
            raw=membership();node=raw['data']['repository']['issue']['projectItems']['nodes'][0]
            if change=='redacted':node.update(type='REDACTED',content=None)
            elif change=='null':raw['data']['repository']['issue']['projectItems']['nodes'][0]=None
            elif change=='foreign_issue':node['content']['number']=8
            else:node['content']['repository']['databaseId']=102
            with self.subTest(change=change):self.unknown(Fixture(members=[raw]))
    def test_wrong_field_type_project_id_or_deleted_field_never_becomes_zero(self):
        for change in ('number','multi','foreign','deleted','wrong_id'):
            raw=membership();selected=raw['data']['priorityField']
            if change=='number':selected.update(__typename='ProjectV2Field',dataType='NUMBER')
            elif change=='multi':selected.update(__typename='ProjectV2MultiSelectField',dataType='MULTI_SELECT')
            elif change=='foreign':selected['project']['id']='PVT_other'
            elif change=='wrong_id':selected['id']='PVTSSF_other'
            else:raw['data']['priorityField']=None
            with self.subTest(change=change):self.unknown(Fixture(members=[raw]))
    def test_unknown_or_unregistered_option_is_unavailable(self):
        for option in ('option-not-current','option-new'):
            raw=values([value(option)])
            if option=='option-new':raw['data']['priorityField']['options'].append({'id':option})
            with self.subTest(option=option):self.unknown(Fixture(fields=[raw]))
    def test_missing_nullable_option_key_and_duplicate_field_values_are_unavailable(self):
        missing=value();missing.pop('optionId')
        for nodes in ([missing],[value(),value()]):
            with self.subTest(nodes=nodes):self.unknown(Fixture(fields=[values(nodes)]))
    def test_wrong_selected_field_value_type_is_unavailable(self):
        self.unknown(Fixture(fields=[values([value(typename='ProjectV2ItemFieldTextValue')])]))
    def test_complete_membership_can_find_the_item_on_a_later_page(self):
        first=membership([item('PVTI_other','PVT_other')],total=2,more=True,cursor='members-next')
        second=membership([item()],total=2)
        f=Fixture(members=[first,second]);self.known(f,42)
        self.assertEqual(f.calls[1][1]['variables']['after'],'members-next')
    def test_complete_field_pagination_preserves_selected_value(self):
        first=values([value(identifier='other',typename='ProjectV2ItemFieldTextValue')],total=2,more=True,cursor='fields-next')
        f=Fixture(fields=[first,values([value()],total=2)]);self.known(f,42)
        self.assertEqual(f.calls[2][1]['variables']['after'],'fields-next')
    def test_failed_later_membership_or_field_page_cannot_supply_zero(self):
        for kind in ('members','fields'):
            kwargs={kind:[membership(total=2,more=True,cursor='next') if kind=='members' else values([value(identifier='other',typename='ProjectV2ItemFieldTextValue')],total=2,more=True,cursor='next'),GitHubError('Unavailable')]}
            with self.subTest(kind=kind):self.unknown(Fixture(**kwargs))
    def test_repeated_cursor_overlapping_page_and_incomplete_count_are_unavailable(self):
        repeated=membership([item('PVTI_other','PVT_other')],total=4,more=True,cursor='repeat')
        for rows in ([repeated,repeated],[membership(total=2,more=True,cursor='next'),membership(total=2)],[membership(total=2)]):
            with self.subTest(rows=rows):self.unknown(Fixture(members=rows))
    def test_metadata_or_source_identity_drift_between_reads_is_unavailable(self):
        for change in ('project','field','option','issue_node','repository','item'):
            raw=values()
            if change=='project':raw['data']['project']['id']='PVT_other'
            elif change=='field':raw['data']['priorityField']['id']='PVTSSF_other'
            elif change=='option':raw['data']['priorityField']['options']=[{'id':'option-low'}]
            elif change=='issue_node':raw['data']['repository']['issue']['id']='I_reused'
            elif change=='item':raw['data']['item']['id']='PVTI_other'
            else:raw['data']['repository']['databaseId']=102
            with self.subTest(change=change):self.unknown(Fixture(fields=[raw]))
    def test_provider_errors_permissions_and_missing_project_remain_unknown(self):
        for change in ('errors','permissions','project'):
            raw=membership()
            if change=='errors':raw['errors']=[{'message':CANARY}]
            elif change=='permissions':raw['data']['repository']['viewerPermission']=None
            else:raw['data']['project']=None
            with self.subTest(change=change):self.unknown(Fixture(members=[raw]))
    def test_credential_rotation_cannot_publish_priority_from_mixed_reads(self):
        f=Fixture();f.rotate=True;self.unknown(f)
    def test_tighter_outer_request_and_time_budget_are_preserved(self):
        for seconds,requests in ((15,1),(0,8)):
            f=Fixture()
            with f.client.read_budget(seconds=seconds,requests=requests):self.unknown(f)
            self.assertLessEqual(len(f.calls),requests)
            if not seconds:self.assertEqual(f.calls,[])
    def test_bounded_membership_and_field_collections_do_not_drop_scope(self):
        members=[item('PVTI_'+str(n),'PVT_other') for n in range(254)]+[item()]
        pages=[membership(members[i:i+100],total=255,more=i+100<255,cursor='m'+str(i+100) if i+100<255 else None) for i in range(0,255,100)]
        f=Fixture(members=pages);self.known(f,42);self.assertEqual(len(f.calls),4)
        nodes=[value(identifier='field-'+str(n),typename='ProjectV2ItemFieldTextValue') for n in range(254)]+[value()]
        pages=[values(nodes[i:i+100],total=255,more=i+100<255,cursor='f'+str(i+100) if i+100<255 else None) for i in range(0,255,100)]
        f=Fixture(fields=pages);self.known(f,42);self.assertEqual(len(f.calls),4)
    def test_overflowing_complete_claim_is_not_a_known_priority(self):
        nodes=[value(identifier='field-'+str(n),typename='ProjectV2ItemFieldTextValue') for n in range(255)]
        pages=[values(nodes[i:i+100],total=256,more=True,cursor='f'+str(i+100)) for i in range(0,255,100)]
        self.unknown(Fixture(fields=pages))
    def test_invalid_policy_or_issue_identity_is_rejected_before_api(self):
        for change in ('bool','unknown_key','self_mapping','wrong_source'):
            policy=copy.deepcopy(POLICY)
            if change=='bool':policy['option_priorities'][O]=True
            elif change=='unknown_key':policy['argv']=['untrusted']
            elif change=='self_mapping':policy['priority_field_id']=''
            else:policy['source']='arbitrary'
            f=Fixture()
            with self.subTest(change=change),self.assertRaises((ProjectError,GitHubError,ValueError)):f.read(policy=policy)
            self.assertEqual(f.calls,[])
        f=Fixture()
        with self.assertRaises((GitHubError,ValueError)):f.read(source={'repository_id':True,'issue_number':7})
        self.assertEqual(f.calls,[])
    def test_issue_planning_source_does_not_make_project_calls(self):
        f=Fixture();result=f.read(policy={'source':'issue'});self.assertIsNone(result['priority']);self.assertEqual(f.calls,[])
    def test_unknown_value_shape_and_byte_limit_are_unavailable(self):
        for change in ('unknown_type','bytes'):
            raw=values()
            if change=='unknown_type':raw['data']['item']['fieldValues']['nodes'][0]['__typename']='UnknownFutureValue'
            else:raw['extra']='x'*131073
            with self.subTest(change=change):self.unknown(Fixture(fields=[raw]))
    def test_untrusted_extras_are_not_exported_and_reads_never_write(self):
        raw=membership();raw['untrusted']={'body':CANARY,'command':'mutation { destroy }'}
        f=Fixture(members=[raw]);result=self.known(f,42)
        self.assertNotIn(CANARY,json.dumps(result));self.assertEqual(len(f.calls),2)
    def test_each_read_is_fresh_and_output_is_detached_from_input(self):
        f=Fixture();first=f.client.native_planning_read('example/alpha',SOURCE,POLICY)
        self.assertEqual(first.value['priority'],42);mutated=first.value;mutated['priority']=1000
        self.assertEqual(first.value['priority'],42)
        f.calls=[];f.fields=[values([value('option-low')])];self.assertEqual(f.read()['priority'],-5)
        self.assertEqual(len(f.calls),2)

if __name__=='__main__':unittest.main()
