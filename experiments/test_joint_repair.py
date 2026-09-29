"""Oracle-backed tests for joint tool selection on resource forests."""
import random
import unittest

from experiments.joint_repair import Choice, exhaustive_oracle, solve_tree


class JointRepairTest(unittest.TestCase):
    def test_choice_propagates_across_three_nodes(self):
        options = {
            "a": [Choice("a0", "request", "text", original=True, function_id="a"),
                  Choice("a1", "request", "json", function_id="a")],
            "b": [Choice("b0", "text", "text", original=True, function_id="b"),
                  Choice("b1", "json", "json", function_id="b")],
            "c": [Choice("c0", "text", "answer", original=True, function_id="c"),
                  Choice("c1", "json", "answer", function_id="c")],
        }
        actual = solve_tree(options, [("a", "b"), ("b", "c")], {"a"})
        self.assertTrue(actual.feasible)
        self.assertEqual(actual.changed, {"a", "b", "c"})
        self.assertEqual(actual.cost, 3)

    def test_immutable_boundary_blocks_propagation(self):
        options = {
            "a": [Choice("a0", "x", "y", original=True, function_id="a"),
                  Choice("a1", "x", "z", function_id="a")],
            "b": [Choice("b0", "y", "w", original=True, function_id="b"),
                  Choice("b1", "z", "w", function_id="b")],
        }
        self.assertFalse(solve_tree(options, [("a", "b")], {"a"}, immutable={"b"}).feasible)

    def test_function_filter_rejects_unrelated_implementation(self):
        options = {"a": [Choice("a0", "x", "y", original=True, function_id="weather"),
                         Choice("a1", "x", "y", function_id="stocks")]}
        self.assertFalse(solve_tree(options, [], {"a"}).feasible)
        self.assertTrue(solve_tree(options, [], {"a"}, require_function_match=False).feasible)

    def test_random_forests_match_exhaustive_oracle(self):
        rng = random.Random(20260924)
        types = ("x", "y", "z")
        for trial in range(500):
            n = rng.randint(1, 6)
            edges = [(str(rng.randrange(i)), str(i)) for i in range(1, n)
                     if rng.random() < .8]
            originals = {str(i): [rng.choice(types), rng.choice(types)] for i in range(n)}
            for u, v in edges:
                originals[v][0] = originals[u][1]
            options = {}
            for i in range(n):
                name = str(i)
                function = f"function_{i}"
                options[name] = [Choice(f"{name}_old", *originals[name],
                                        original=True, function_id=function)]
                options[name] += [Choice(f"{name}_{j}", rng.choice(types),
                                         rng.choice(types), change_cost=rng.randint(1, 4),
                                         function_id=function)
                                  for j in range(rng.randint(1, 3))]
            failed = {str(rng.randrange(n))}
            immutable = {str(i) for i in range(n) if str(i) not in failed and rng.random() < .2}
            actual = solve_tree(options, edges, failed, immutable=immutable)
            oracle = exhaustive_oracle(options, edges, failed, immutable=immutable)
            self.assertEqual((actual.feasible, actual.cost, len(actual.changed)),
                             (oracle.feasible, oracle.cost, len(oracle.changed)), trial)


if __name__ == "__main__":
    unittest.main()
