-- Executed by provision_reader with quoted role/database identifiers.
GRANT CONNECT ON DATABASE {database} TO {reader};
GRANT USAGE ON SCHEMA ops TO {reader};
GRANT SELECT ON ops.employees, ops.accounts, ops.devices, ops.software_products,
    ops.software_entitlements, ops.services, ops.service_incidents,
    ops.support_tickets TO {reader};
ALTER ROLE {reader} SET default_transaction_read_only = on;
ALTER ROLE {reader} SET statement_timeout = '5s';
ALTER ROLE {reader} SET search_path = pg_catalog;
