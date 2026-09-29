import unittest
from experiments.repair_region import Edge,least_region,minimum_assignment


class RegionTests(unittest.TestCase):
    def test_forward_representation_change_requires_consumer(self):
        r=least_region('abc',[Edge('a','b',ok_10=False),Edge('b','c')],{'a'})
        self.assertEqual(r.nodes,{'a','b'});self.assertTrue(r.feasible)

    def test_new_consumer_can_require_upstream_repair(self):
        r=least_region('abc',[Edge('a','b',ok_01=False),Edge('b','c')],{'b'})
        self.assertEqual(r.nodes,{'a','b'})

    def test_join_requires_only_incompatible_branch(self):
        r=least_region('abcd',[Edge('a','c',ok_10=False),Edge('b','c',ok_01=False),Edge('c','d')],{'a'})
        self.assertEqual(r.nodes,{'a','b','c'})

    def test_committed_node_cannot_be_silently_replayed(self):
        r=least_region('ab',[Edge('a','b',ok_01=False)],{'b'},immutable={'a'})
        self.assertFalse(r.feasible);self.assertIn('immutable_required',r.reasons[0])

    def test_internal_mismatch_makes_assignment_infeasible(self):
        r=least_region('ab',[Edge('a','b',ok_10=False,ok_11=False)],{'a'})
        self.assertFalse(r.feasible)

    def test_minimum_is_over_only_supplied_assignments(self):
        r=minimum_assignment('ab',[('co_repair',[Edge('a','b',ok_10=False)]),
                                    ('compatible',[Edge('a','b')])],{'a'})
        self.assertEqual(r[:2],(1,'compatible'))


if __name__=='__main__':unittest.main()
