"""验收材料完整性测试，不把 AI 标签等价于人工标签。"""
import copy
import pytest
from agent_governance.evolution.acceptance_audit import (
    claim_review, canonical_snapshot, digest, order_comparison, admission_decision)

def authority_projection(value):
    return canonical_snapshot(value, {'model_version','created_at','latency_ms'})


def context():
    return {'replan_result':{'candidate_plan':{'plan_id':'a', 'model_version':'x',
            'status':'PENDING', 'valid_until':'2030', 'schedule':[]}}, 'constraint_set':{'soc':.3}}


def test_ai_review_never_signed():
    r=claim_review('本次候选已经执行。', {'execution_confirmed':False})
    assert r['prediction']=='CONTRADICTED'
    assert r['label_origin']=='AI_DRAFT' and r['review_status']=='HOLD'
    assert all(r[k] is None for k in ('human_label','reviewer_id','signature','reviewed_at'))
    assert r['claims'][0]['scope_method']=='SCORER_CLAUSE_PENDING_HUMAN_REVIEW'


@pytest.mark.parametrize('key', ['plan_id','model_version','trace_id','request_id','created_at','latency_ms'])
def test_irrelevant_metadata_does_not_create_family(key):
    a=context(); b=copy.deepcopy(a); b['replan_result']['candidate_plan'][key]='different'
    assert digest(authority_projection(a))==digest(authority_projection(b))


@pytest.mark.parametrize('key,value',[('status','ACTIVE'),('valid_until','2031')])
def test_authority_state_still_matters(key,value):
    a=context(); b=copy.deepcopy(a); b['replan_result']['candidate_plan'][key]=value
    assert digest(authority_projection(a))!=digest(authority_projection(b))


def test_no_snapshot_not_clean_result():
    with pytest.raises(ValueError): authority_projection({})


@pytest.mark.parametrize('a,b,consistent',[('A','B',True),('B','A',True),('A','A',False),
    ('TIE','TIE',True),('UNCERTAIN','UNCERTAIN',False)])
def test_order_mapping(a,b,consistent):
    assert order_comparison(a,b)['order_consistent']==consistent


@pytest.mark.parametrize('index',range(5))
def test_each_missing_gate_blocks(index):
    args=['PASS','PASS','PASS','PASS','YES']; args[index]='HOLD'
    r=admission_decision(*args)
    assert r['EXPERIMENT_04']=='HOLD' and not r['candidate_generated']


def test_gate_does_not_generate_candidate():
    r=admission_decision('PASS','PASS','PASS','PASS','YES')
    assert r['EXPERIMENT_04']=='READY_FOR_FROZEN_EVALUATION' and not r['candidate_generated']
