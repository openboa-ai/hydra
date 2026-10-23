"""Bounded optional Project priority; no source activation or execution grant.

The caller owns registration and protected policy provenance. A returned value
is a read observation, never delegated authority or requirement acceptance.
"""
import copy
from dataclasses import dataclass
from datetime import datetime,timezone
import json
from .github import GitHubError,_repo
from .github_relations import _source,_node,_text,_integer,_require,_Unavailable
from .project import _planning
from .work_records import _issue_ref

MAX_ITEMS=255
MAX_PAGES=3
_COMMON='field{... on ProjectV2FieldCommon{id dataType project{id}}}'
_OTHER_TYPES=('ProjectV2ItemFieldLabelValue','ProjectV2ItemFieldMilestoneValue',
 'ProjectV2ItemFieldPullRequestValue','ProjectV2ItemFieldRepositoryValue',
 'ProjectV2ItemFieldReviewerValue','ProjectV2ItemFieldUserValue','ProjectV2ItemIssueFieldValue')
_COMMON_TYPES=('ProjectV2ItemFieldDateValue','ProjectV2ItemFieldIterationValue',
 'ProjectV2ItemFieldMultiSelectValue','ProjectV2ItemFieldNumberValue',
 'ProjectV2ItemFieldSingleSelectValue','ProjectV2ItemFieldTextValue')
_VALUE_TYPES=set(_COMMON_TYPES+_OTHER_TYPES)
_ISSUE='id number repository{databaseId nameWithOwner isPrivate viewerPermission}'
_ITEM='__typename id type project{id} content{__typename ... on Issue{'+_ISSUE+'}}'
_PINS=('project:node(id:$project){__typename ... on ProjectV2{id}} '
 'priorityField:node(id:$field){__typename ... on ProjectV2SingleSelectField{'
 'id dataType project{id} options{id}}}')
_ROOT='repository(owner:$owner,name:$name){databaseId nameWithOwner isPrivate viewerPermission issue(number:$number){id number '
_VARS='$owner:String!,$name:String!,$number:Int!,$project:ID!,$field:ID!,$first:Int!,$after:String'
_MEMBERS=('query HydraNativePlanningMembership('+_VARS+'){'+_ROOT+
 'projectItems(includeArchived:true,first:$first,after:$after){totalCount nodes{'+_ITEM+
 '} pageInfo{hasNextPage endCursor}}}} '+_PINS+'}')
_VALUE_FIELDS=('__typename ... on ProjectV2ItemFieldValueCommon{'+_COMMON+'} '+
 ' '.join('... on '+kind+'{'+_COMMON+'}' for kind in _OTHER_TYPES)+
 ' ... on ProjectV2ItemFieldSingleSelectValue{optionId}')
_VALUES=('query HydraNativePlanningValues('+_VARS+',$item:ID!){'+_ROOT+'}} '+_PINS+
 ' item:node(id:$item){... on ProjectV2Item{'+_ITEM+
 ' fieldValues(first:$first,after:$after){totalCount nodes{'+_VALUE_FIELDS+
 '} pageInfo{hasNextPage endCursor}}}}}')

@dataclass(frozen=True)
class PlanningRead:
    document:str
    @property
    def value(self):return json.loads(self.document)

def result(source,planning,coverage='unavailable',priority=None,reason='planning_unavailable'):
    return PlanningRead(json.dumps({'source':source,'project_id':planning.get('project_id'),
        'priority_field_id':planning.get('priority_field_id'),'coverage':coverage,'priority':priority,
        'reason':reason,'observed_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')},sort_keys=True,separators=(',',':')))

def read_priority(client,repository,source,planning):
    """Read the explicitly selected field, with no fallback or implicit grant."""
    _repo(repository);_issue_ref(source)
    source=copy.deepcopy(source)
    policy=copy.deepcopy(_planning({'work_source':'github_native','planning':planning}))
    if policy['source']!='github_project':return result(source,policy,reason='planning_not_selected')
    owner,name=repository.split('/');identity=None;credential=None;observed=False
    def read(query,after,limit,item=None):
        nonlocal identity,credential,observed
        variables={'owner':owner,'name':name,'number':source['issue_number'],
                   'project':policy['project_id'],'field':policy['priority_field_id'],
                   'first':limit,'after':after}
        if item is not None:variables['item']=item
        raw=client.api('POST','/graphql',{'query':query,'variables':variables})
        client._request_timeout(15)
        issue,current=_source(raw,repository,source)
        data=raw['data'];project=data.get('project');field=data.get('priorityField')
        _require(type(project) is dict and project.get('__typename')=='ProjectV2' and project.get('id')==policy['project_id'])
        _require(type(field) is dict and field.get('__typename')=='ProjectV2SingleSelectField'
                 and field.get('id')==policy['priority_field_id'] and field.get('dataType')=='SINGLE_SELECT')
        _require(type(field.get('project')) is dict and field['project'].get('id')==policy['project_id'])
        options=field.get('options');_require(type(options) is list and len(options)<=100)
        option_ids=[]
        for option in options:
            _require(type(option) is dict);option_ids.append(_text(option.get('id'),200))
        _require(len(set(option_ids))==len(option_ids))
        _require(set(policy['option_priorities']) <= set(option_ids))
        context=current,tuple(sorted(option_ids))
        current_credential=client._authenticated_fingerprint
        if identity is not None:
            _require(context==identity and current_credential==credential)
        else:identity,credential=context,current_credential
        observed=True
        return data,issue,current,set(option_ids)
    def item_identity(value,current):
        _require(type(value) is dict and value.get('__typename')=='ProjectV2Item' and value.get('type')=='ISSUE')
        identifier=_text(value.get('id'),200);project=value.get('project');content=value.get('content')
        _require(type(project) is dict);project_id=_text(project.get('id'),200)
        _require(type(content) is dict and content.get('__typename')=='Issue')
        ref,node,repository_identity=_node(content)
        _require(ref==source and node==current[1] and repository_identity==current[0])
        return identifier,project_id
    def page(value,limit,after,cursors):
        _require(type(value) is dict)
        total=_integer(value.get('totalCount'));nodes=value.get('nodes');info=value.get('pageInfo')
        _require(type(nodes) is list and len(nodes)<=limit and type(info) is dict)
        _require(type(info.get('hasNextPage')) is bool and 'endCursor' in info)
        more,cursor=info['hasNextPage'],info['endCursor']
        if cursor is not None:_text(cursor,2048)
        if more:_require(nodes and cursor is not None and cursor!=after and cursor not in cursors)
        return nodes,total,more,cursor
    try:
        with client.read_budget(seconds=15,requests=8):
            selected=[];seen=set();cursors=set();after=None;expected=None
            for _ in range(MAX_PAGES):
                limit=min(100,MAX_ITEMS-len(seen));_require(limit>0)
                _,issue,current,_=read(_MEMBERS,after,limit)
                nodes,total,more,cursor=page(issue.get('projectItems'),limit,after,cursors)
                _require(expected is None or expected==total);expected=total
                for node in nodes:
                    identifier,project=item_identity(node,current);_require(identifier not in seen);seen.add(identifier)
                    if project==policy['project_id']:selected.append(identifier)
                _require(len(selected)<=1 and len(seen)<=total)
                if not more:_require(len(seen)==total);break
                _require(len(seen)<MAX_ITEMS);cursors.add(cursor);after=cursor
            else:raise _Unavailable()
            _require(len(selected)==1)
            selected=selected[0];seen=set();cursors=set();after=None;expected=None;priority=None
            for _ in range(MAX_PAGES):
                limit=min(100,MAX_ITEMS-len(seen));_require(limit>0)
                data,_,current,options=read(_VALUES,after,limit,selected)
                value=data.get('item');identifier,project=item_identity(value,current)
                _require(identifier==selected and project==policy['project_id'])
                nodes,total,more,cursor=page(value.get('fieldValues'),limit,after,cursors)
                _require(expected is None or expected==total);expected=total
                for node in nodes:
                    _require(type(node) is dict and type(node.get('__typename')) is str
                             and node['__typename'] in _VALUE_TYPES)
                    field=node.get('field');_require(type(field) is dict)
                    identifier=_text(field.get('id'),200);_text(field.get('dataType'),60)
                    _require(type(field.get('project')) is dict and field['project'].get('id')==policy['project_id'])
                    _require(identifier not in seen);seen.add(identifier)
                    if identifier==policy['priority_field_id']:
                        _require(node['__typename']=='ProjectV2ItemFieldSingleSelectValue'
                                 and field['dataType']=='SINGLE_SELECT' and 'optionId' in node)
                        option=node['optionId']
                        if option is None:priority=0
                        else:
                            _text(option,200);_require(option in options and option in policy['option_priorities'])
                            priority=policy['option_priorities'][option]
                _require(len(seen)<=total)
                if not more:
                    _require(len(seen)==total);client._request_timeout(15)
                    complete=result(source,policy,'complete',0 if priority is None else priority,None)
                    client._request_timeout(15)
                    return complete
                _require(len(seen)<MAX_ITEMS);cursors.add(cursor);after=cursor
            raise _Unavailable()
    except (GitHubError,_Unavailable,OSError):
        return result(source,policy,'partial' if observed else 'unavailable')
