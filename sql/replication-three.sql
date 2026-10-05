-- Small-cluster policy: three voting copies, including system ranges.
-- Run only after at least three live CockroachDB nodes have joined.
-- This deliberately reduces the vendor's five-copy critical-system defaults.
ALTER RANGE default CONFIGURE ZONE USING num_replicas = 3;
ALTER DATABASE system CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE meta CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE system CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE liveness CONFIGURE ZONE USING num_replicas = 3;
