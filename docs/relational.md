# Relational recovery

`Snapshot(rows)` privately copies JSON row objects and builds a non-null value
index. `Projection(name, source, target, cost=1)` describes a unary lookup of one
column from another in that snapshot. A projection is not an adapter to arbitrary
remote code. `RelationalRecovery(snapshot, tools)` owns a reviewed finite catalog.

## Evidence and equality

A lookup finds rows matching the input column and requires exactly one distinct
non-null output value. Duplicate identical results are allowed. Missing fields and
JSON `null` mean unavailable cells; they are not tool exceptions. An absent input,
absent result or multiple distinct results causes rejection.

Values use canonical JSON equality, retaining JSON type distinctions. Boolean
`true` and number `1`, or string `"1"` and number `1`, are distinct. Object key order
is ignored. Number `1` and number `1.0` are distinct representations. NaN/infinity
and non-JSON values are rejected. There are no implicit conversions, normalization
rules, rounding or hidden lookup state. If your tools normalize values, perform
that normalization explicitly before constructing the snapshot and adapters.

An observed-input certificate checks:

1. The route starts at the declared source column, composes through matching column
   boundaries and ends at the declared target column.
2. Each lookup is single-valued and defined for the actual intermediate value.
3. The route output equals the direct trusted source-to-target lookup.
4. At least one common record witnesses all the intermediate values and boundaries.

The certificate binds input, output, route IDs, row witnesses and snapshot/catalog
SHA-256 digests. These are consistency identities, not cryptographic signatures
from an independent authority. They reveal values and row IDs: treat packets as
application data when logging or sharing them.

`mode="global"` additionally validates single-valued dependencies for every
non-null source of each projection and successful route evidence for every
non-null input in the target source column. It is intentionally more restrictive
than observed-input admission on sparse relations.

## Route selection and exclusions

```python
admission, rejected = engine.repair(
    source="customer", target="balance", value="Ada",
    excluded={"failed_direct_tool"}, max_hops=4,
    max_candidates=1000, max_expansions=100_000,
)
```

Exclude failed tool IDs explicitly; unknown exclusions are errors. The search
considers simple column paths with at most `max_hops` calls, ranked by total cost,
hop count and stable tool IDs. It tests candidates in that order, so a cheaper
invalid route cannot hide a more expensive certified route. `rejected` records
reasons for the cheaper routes that were tested and rejected. No admitted route
means none was found within the declared path bounds, not universal impossibility.
Candidate and search-expansion limits raise rather than return a partial optimum.
Zero-length identity routes and cyclic routes are not searched.

For a specific route, `engine.certify(source, target, value, path)` returns
`Admission(admitted, reason, certificate)`. Typical rejection reasons include
`missing_value`, `ambiguous_value`, `incompatible_path`, `wrong_target_operation`,
`target_value_mismatch` and `no_common_record_witness`.

## Snapshot updates and execution

```python
fresh_snapshot = Snapshot(load_rows_in_one_consistent_read())
value = engine.execute(certificate, current_snapshot=fresh_snapshot)
```

Execution rejects a different snapshot digest, even if this input's target value
happens to be unchanged. It revalidates the full certificate and performs the path
lookups on the supplied snapshot. For updated data, construct a new engine with
that snapshot, obtain a new certificate, then execute it.

If `current_snapshot` is omitted, execution uses the engine's original private
snapshot. That does not detect changes in an external database. Applications must
acquire a transactionally consistent read and pass its snapshot to check freshness.
Remote tools are not invoked by this API. An HTTP integration needs an independently
checked adapter that actually obeys these projection and snapshot semantics.
The workflow executor's interface checks and this relational value certificate
are separate interfaces; workflow plans do not automatically contain value proofs.
