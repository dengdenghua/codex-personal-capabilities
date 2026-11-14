import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from optics_workbench.graph import EvidenceGraph
from optics_workbench.core import Workbench
from optics_workbench.mcp_server import MCPServer


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.g = EvidenceGraph(self.base/'graph.sqlite3')
        self.sha='a'*64
        self.catalog=self.base/'catalog.json'; self.audit=self.base/'audit.json'
        self.rules=[dict(id='r1',source_id='DEMO',source_sha256=self.sha,statement='Synthetic observation only',location='demo p1',conditions_and_missing_evidence='Wavelength and uncertainty are unspecified',adoption_status='not_adopted',full_model_validated=False)]
        self.write_files()
        self.docs={self.sha:dict(title='Synthetic demo',status='registered_partial_review',paths='[]')}

    def write_files(self):
        self.catalog.write_text(json.dumps(dict(round=1,rules=self.rules)),encoding='utf-8')
        self.audit.write_text(json.dumps(dict(catalog_sha256=hashlib.sha256(self.catalog.read_bytes()).hexdigest(),records=[dict(id='DEMO',sha256=self.sha,read_scope='Synthetic fixture only')])),encoding='utf-8')

    def seed(self):return self.g.import_catalog(self.catalog,self.audit,'Demo',self.docs)

    def test_idempotent_graph_and_durable_memory(self):
        self.seed(); self.seed(); self.assertEqual(self.g.stats()['edges'],3)
        rid='round-1:r1'; m=self.g.remember('engineering_lesson','Check uncertainties','Demo only','Reviewed fixture',[rid]); self.g.remember('engineering_lesson','Check uncertainties','Demo only','Reviewed fixture',[rid])
        reopened=EvidenceGraph(self.g.path);self.assertEqual(reopened.stats()['memories'],1)
        self.assertEqual(reopened.memories()['items'][0]['status'],'reviewed_conditional')
        graph=self.g.neighborhood(rid);self.assertEqual(len(graph['nodes']),4)
        self.assertTrue(any(n['kind']=='conditions_and_gaps' for n in graph['nodes']))
        self.assertEqual(m['node_ids'],[rid])

    def test_invalid_source_or_hash_cannot_partially_import(self):
        self.rules.append({**self.rules[0],'id':'r2','source_id':'missing'});self.write_files()
        with self.assertRaises(ValueError):self.seed()
        self.assertEqual(self.g.stats()['nodes'],0)
        self.catalog.write_text('{}')
        with self.assertRaises(ValueError):self.seed()
        self.assertEqual(self.g.stats()['edges'],0)

    def test_no_silent_replacement_or_unreviewed_promotions(self):
        self.seed();self.rules[0]['statement']='Changed claim';self.write_files()
        with self.assertRaises(ValueError):self.seed()
        self.assertEqual(self.g.search()['items'][0]['title'],'Synthetic observation only')
        self.docs[self.sha]['status']='unread_or_no_registered_review'
        with self.assertRaises(ValueError):self.seed()

    def test_memory_rejects_unsourced_or_dangling_engineering_lessons(self):
        for nodes in ([],['missing']):
            with self.assertRaises(ValueError):self.g.remember('engineering_lesson','Claim','Scope','Origin',nodes)
        self.assertEqual(self.g.stats()['memories'],0)
        with self.assertRaises(ValueError):self.g.search('%',True)
        self.assertEqual(self.g.search('%')['items'],[])

    def test_full_text_review_requires_explicit_audit_and_retains_extent(self):
        self.docs[self.sha]['status']='registered_full_text_review'
        audit=json.loads(self.audit.read_text())
        for value in (None,False,'true',1):
            audit['records'][0]['full_document_read']=value
            self.audit.write_text(json.dumps(audit),encoding='utf8')
            with self.assertRaises(ValueError):self.seed()
            self.assertEqual(self.g.stats()['nodes'],0)
        audit['records'][0]['full_document_read']=True
        self.audit.write_text(json.dumps(audit),encoding='utf8')
        self.seed()
        source=next(n for n in self.g.neighborhood('round-1:r1')['nodes'] if n['kind']=='source')
        self.assertIs(source['payload']['full_document_read'],True)
        self.assertIs(source['payload']['full_model_validated'],False)
        self.assertIs(source['review_scopes'][0]['payload']['full_document_read'],True)

    def test_full_reading_cannot_promote_validation_or_adoption(self):
        self.docs[self.sha]['status']='registered_full_text_review'
        for key,value in [('full_model_validated',True),('adoption_status','adopted')]:
            self.rules[0][key]=value;self.write_files()
            audit=json.loads(self.audit.read_text());audit['records'][0]['full_document_read']=True
            self.audit.write_text(json.dumps(audit),encoding='utf8')
            with self.assertRaises(ValueError):self.seed()
            self.assertEqual(self.g.stats()['nodes'],0)
            self.rules[0].update(full_model_validated=False,adoption_status='not_adopted')

    def test_mcp_routes_and_readonly_memory_guard(self):
        wb=Workbench(data_dir=self.base/'workbench'); server=MCPServer(wb)
        result=server._call('optics_remember',dict(kind='user_preference',text='Use evidence links',scope='Demo',provenance='Synthetic user request'))
        self.assertEqual(result['status'],'user_stated')
        self.assertEqual(server._call('optics_search_memory',{})['items'][0]['text'],'Use evidence links')
        from optics_workbench.mcp_server import TOOL_MAP
        self.assertFalse(TOOL_MAP['optics_remember']['annotations']['readOnlyHint'])
        self.assertTrue(TOOL_MAP['optics_search_graph']['annotations']['readOnlyHint'])

    def test_source_correction_survives_reimport_and_is_visible(self):
        self.seed()
        original = self.g.neighborhood('round-1:r1')['nodes']
        catalog = self.base/'correction.json'; audit = self.base/'correction-audit.json'
        rule = {**self.rules[0], 'id':'c1', 'statement':'Rechecked source corrects one angle', 'corrects':['round-1:r1']}
        catalog.write_text(json.dumps(dict(round=2,rules=[rule])),encoding='utf8')
        audit.write_text(json.dumps(dict(catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest(),records=[dict(id='DEMO',sha256=self.sha,read_scope='Rechecked source p1')])),encoding='utf8')
        self.g.import_catalog(catalog,audit,'Correction',self.docs); self.seed()
        old = next(n for n in self.g.search('Synthetic observation')['items'] if n['id']=='round-1:r1')
        self.assertEqual(old['title'],'Synthetic observation only')
        self.assertEqual(old['corrections'][0]['id'],'round-2:c1')
        self.assertEqual(old['review_status'],'has_source_backed_correction')
        neighborhood = self.g.neighborhood(old['id'])
        self.assertTrue(any(e['relation']=='corrects' for e in neighborhood['edges']))
        self.g.import_catalog(catalog,audit,'Correction',self.docs)
        self.assertEqual(self.g.stats()['edges'],7)

    def test_invalid_correction_target_cannot_partially_import(self):
        self.rules[0]['corrects']=['missing'];self.write_files()
        with self.assertRaises(ValueError):self.seed()
        self.assertEqual(self.g.stats()['nodes'],0)
        self.assertEqual(self.g.stats()['edges'],0)

    def test_supplementary_review_preserves_original_source_and_both_scopes(self):
        self.seed()
        sid = 'source:' + self.sha
        with self.g.connect() as db:
            original = tuple(db.execute('SELECT * FROM nodes WHERE id=?', (sid,)).fetchone())
        rule = {**self.rules[0], 'id': 'supplement', 'source_id': 'SUPPLEMENT'}
        self.catalog.write_text(json.dumps(dict(round=2, rules=[rule])), encoding='utf8')
        self.audit.write_text(json.dumps(dict(
            catalog_sha256=hashlib.sha256(self.catalog.read_bytes()).hexdigest(),
            records=[dict(id='SUPPLEMENT', sha256=self.sha, read_scope='Second, independently limited scope')]
        )), encoding='utf8')
        self.g.import_catalog(self.catalog, self.audit, 'Supplement', self.docs)
        self.g.import_catalog(self.catalog, self.audit, 'Supplement', self.docs)
        with self.g.connect() as db:
            self.assertEqual(original, tuple(db.execute('SELECT * FROM nodes WHERE id=?', (sid,)).fetchone()))
        source = next(n for n in self.g.neighborhood(sid)['nodes'] if n['id'] == sid)
        self.assertEqual([(x['batch'], x['record_id'], x['payload']['read_scope']) for x in source['review_scopes']],
                         [('round-1', 'DEMO', 'Synthetic fixture only'),
                          ('round-2', 'SUPPLEMENT', 'Second, independently limited scope')])
        self.assertEqual(self.g.stats()['nodes'], 7)
        reopened = EvidenceGraph(self.g.path)
        self.assertEqual(source['review_scopes'], next(n for n in reopened.search('Synthetic demo')['items'] if n['id'] == sid)['review_scopes'])

    def test_database_guard_preserves_source_when_legacy_client_reimports(self):
        self.seed()
        sid = 'source:' + self.sha
        with self.g.connect() as db:
            original = tuple(db.execute('SELECT * FROM nodes WHERE id=?', (sid,)).fetchone())
            legacy = (sid, 'source', 'Legacy title', '{"read_scope":"Older overwritten scope"}', 'old-round')
            db.execute('INSERT INTO nodes VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload', legacy)
            self.assertEqual(original, tuple(db.execute('SELECT * FROM nodes WHERE id=?', (sid,)).fetchone()))
        self.assertEqual(self.g.stats()['nodes'], 4)


if __name__=='__main__':unittest.main()
