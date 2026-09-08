-- Administrator-only provisioning AFTER migration 0005. No admin URL goes to worker.
-- Supply WORKER_PASSWORD in this psql process's environment, never in source control.
\getenv worker_password WORKER_PASSWORD
ALTER ROLE flare_worker PASSWORD :'worker_password';
