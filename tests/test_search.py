import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reader_client import Client,GhError
from search_client import search

NODE={'number':12,'title':'A result','repository_url':'https://api.github.com/repos/a/b','state':'open','updated_at':'2026-09-08T00:00:00Z'}
class SearchTests(unittest.TestCase):
    def client(self,response=None):
        calls=[]
        def runner(args,payload):
            calls.append((args,payload))
            self.assertEqual(args[4],'GET')
            if args[5]=='user': return json.dumps({'login':'viewer'})
            if isinstance(response,Exception): raise response
            return json.dumps(response or {'items':[NODE],'total_count':1})
        return Client(runner),calls
    def test_query_is_encoded_and_filters_apply_to_entire_expression(self):
        client,calls=self.client()
        search({'query':'one OR two "$(literal)"','repo':'a/b','kind':'pr','state':'open'},client)
        params=parse_qs(urlparse(calls[0][0][5]).query)
        self.assertEqual(params['q'],['(one OR two "$(literal)") repo:a/b is:pr is:open'])
        self.assertEqual(params['advanced_search'],['true'])
        self.assertIsNone(calls[0][1])
    def test_results_resolve_to_reader_targets(self):
        client,calls=self.client({'items':[NODE,{**NODE,'number':13,'pull_request':{'merged_at':'now'},'state':'closed'}],'total_count':2})
        result=search({'repo':'a/b'},client)
        self.assertEqual([(x['kind'],x['repo'],x['number'],x['state']) for x in result['items']],
                         [('issue','a/b',12,'OPEN'),('pull-request','a/b',13,'MERGED')])
    def test_me_qualifiers_use_authenticated_viewer(self):
        client,calls=self.client()
        search({'query':'assignee:@me review-requested:@me'},client)
        self.assertEqual(calls[0][0][5],'user')
        self.assertEqual(parse_qs(urlparse(calls[1][0][5]).query)['q'],['(assignee:viewer review-requested:viewer)'])
    def test_pagination_and_cap_are_explicit(self):
        client,calls=self.client({'items':[NODE],'total_count':2000,'incomplete_results':True})
        first=search({'repo':'a/b'},client)
        self.assertTrue(first['hasMore']);self.assertIn('incomplete',first['warning']);self.assertIn('1,000',first['warning'])
        last=search({'repo':'a/b','page':20},client)
        self.assertFalse(last['hasMore'])
        self.assertEqual(parse_qs(urlparse(calls[-1][0][5]).query)['page'],['20'])
    def test_invalid_input_never_calls_github(self):
        for request in [{},{'repo':'a/b/../../x'},{'repo':'a/b','page':True},{'repo':'a/b','page':21},
                        {'repo':'a/b','kind':'issue','state':'merged'},{'query':'x','kind':'code'}]:
            client,calls=self.client()
            with self.subTest(request=request),self.assertRaises(GhError): search(request,client)
            self.assertEqual(calls,[])
    def test_empty_results_and_permission_errors(self):
        client,_=self.client({'items':[],'total_count':0})
        result=search({'query':'missing'},client)
        self.assertEqual(result['items'],[]);self.assertFalse(result['hasMore'])
        client,calls=self.client(GhError('Rate limit exceeded'))
        with self.assertRaisesRegex(GhError,'Rate limit'): search({'query':'x'},client)
        self.assertEqual(len(calls),1)
    def test_untrusted_repository_url_is_rejected(self):
        client,_=self.client({'items':[{**NODE,'repository_url':'https://example.com/repos/a/b'}],'total_count':1})
        with self.assertRaises(GhError): search({'query':'x'},client)

if __name__=='__main__':unittest.main()
