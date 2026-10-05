-- One-time conversion of zone overrides created by start-single-node.
-- Run after converting to `start`. With fewer than 3 live database nodes,
-- ranges remain under-replicated; this alone does not provide high availability.
ALTER RANGE default CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE meta CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE system CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE timeseries CONFIGURE ZONE USING num_replicas = 3;
ALTER RANGE liveness CONFIGURE ZONE USING num_replicas = 3;
ALTER DATABASE system CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.lease CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.replication_constraint_stats CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.replication_stats CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.statement_statistics CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.transaction_statistics CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.tenant_usage CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.span_stats_tenant_boundaries CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.statement_activity CONFIGURE ZONE USING num_replicas = 3;
ALTER TABLE system.public.transaction_activity CONFIGURE ZONE USING num_replicas = 3;
