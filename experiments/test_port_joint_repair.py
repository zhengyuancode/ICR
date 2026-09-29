import random
import unittest

from experiments.port_joint_repair import PortChoice, solve_ports, exhaustive_ports


class PortJointRepairTests(unittest.TestCase):
    def test_diamond_forces_four_node_closure(self):
        C = PortChoice
        options = {
            "a": [C("ao", ("x",), "x", original=True, function_id="a"),
                  C("an", ("x",), "y", function_id="a")],
            "b": [C("bo", ("x",), "x", original=True, function_id="b"),
                  C("bn", ("y",), "y", function_id="b")],
            "c": [C("co", ("x",), "x", original=True, function_id="c"),
                  C("cn", ("y",), "y", function_id="c")],
            "d": [C("do", ("x", "x"), "z", original=True, function_id="d"),
                  C("dn", ("y", "y"), "z", function_id="d")],
        }
        edges = [("a", "b", 0), ("a", "c", 0), ("b", "d", 0), ("c", "d", 1)]
        answer = solve_ports(options, edges, {"a"})
        self.assertTrue(answer.feasible)
        self.assertEqual(answer.changed, frozenset(options))
        self.assertEqual(answer.max_width, 2)
        self.assertEqual(answer.cost, 4)
        self.assertFalse(solve_ports(options, edges, {"a"}, immutable={"d"}).feasible)

    def test_random_dags_agree_with_exhaustive(self):
        rng = random.Random(20260924)
        for _ in range(300):
            count = rng.randint(2, 6)
            edges = []
            parents = [[] for _ in range(count)]
            for target in range(1, count):
                sources = rng.sample(range(target), rng.randint(0, min(2, target)))
                for port, source in enumerate(sources):
                    edges.append((str(source), str(target), port))
                    parents[target].append(source)
            choices = {}
            for node in range(count):
                name = str(node)
                inputs = tuple("x" for _ in range(max(1, len(parents[node]))))
                choices[name] = [PortChoice(f"{name}:old", inputs, "x", original=True,
                                            function_id=name)]
                for option in range(2):
                    variant_inputs = tuple(rng.choice(("x", "y")) for _ in inputs)
                    choices[name].append(PortChoice(f"{name}:{option}", variant_inputs,
                                                    rng.choice(("x", "y")),
                                                    change_cost=rng.randint(1, 4),
                                                    function_id=name))
            failed = {str(rng.randrange(count))}
            immutable = {str(rng.randrange(count))} - failed if rng.random() < .2 else set()
            exact = solve_ports(choices, edges, failed, immutable=immutable)
            oracle = exhaustive_ports(choices, edges, failed, immutable=immutable)
            self.assertEqual((exact.feasible, exact.cost, len(exact.changed)),
                             (oracle.feasible, oracle.cost, len(oracle.changed)))


if __name__ == "__main__":
    unittest.main()
