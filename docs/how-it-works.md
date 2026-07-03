# How it works

The README covers what the pipeline is and how to deploy it. This document
explains how each piece actually works and why it is built the way it is. I
wrote it as study material for myself: every section ends with the concepts
it demonstrates, and the last section maps the whole project onto the
SAA-C03 exam domains.

Read it with the code open. Each section names the files it describes.

## 1. The agent (`agent/pi_telemetry_agent/`)

The agent is a small Python package with four modules, each with one job:

| Module | Job |
|---|---|
| `collector.py` | Build one telemetry payload from the live system |
| `config.py` | Load and validate configuration |
| `publisher.py` | Deliver a payload (stdout or MQTT) |
| `agent.py` | The loop: collect, publish, sleep, repeat |

### Collection

`collect()` gathers CPU percent, load averages, memory, disk, and uptime
from psutil. CPU temperature is different: psutil's sensor support is
inconsistent across platforms, so `read_cpu_temp_c()` goes to the kernel
directly. Linux exposes thermal sensors as directories under
`/sys/class/thermal/thermal_zone*`, each with a `type` file (the Pi's is
`cpu-thermal`) and a `temp` file in millidegrees Celsius. The reader prefers
a zone whose type mentions "cpu", falls back to the first zone, then to
psutil, and returns `None` when nothing plausible exists. Readings outside
-20 to 130 C are treated as sensor errors and discarded, so a broken sensor
degrades to a missing field instead of poisoning the data downstream.

Every payload carries `schema_version` (so consumers can handle format
changes later), `device_id`, an ISO 8601 UTC `timestamp` for humans, and
`epoch_ms` for machines. Having both is deliberate: `epoch_ms` is the
DynamoDB sort key and makes range queries trivial, while the ISO string
makes items readable in the console.

### Configuration

`config.py` implements a three-layer precedence: environment variables
(prefix `PI_TELEMETRY_`, for example `PI_TELEMETRY_MQTT_ENDPOINT`) override
the YAML file, which overrides dataclass defaults. Defaults are derived
where possible: `device_id` falls back to the hostname, the topic to
`telemetry/<device_id>`, the MQTT client id to `device_id`. That last
default matters more than it looks: the IoT policy (section 3) only allows
connecting as the device's own client id, so a mismatched client id is
rejected at connect time.

`validate()` fails fast at startup with a clear message (missing cert file,
bad interval) rather than letting the agent limp along and fail at publish
time.

### Publishing

`publisher.py` defines a `Publisher` protocol with two implementations.
`StdoutPublisher` prints JSON lines, which is how `make run-once` works with
zero AWS setup. `MqttPublisher` wraps paho-mqtt:

- **Mutual TLS.** `tls_set()` gets three files: the Amazon root CA (so the
  agent can verify it is talking to the real AWS endpoint), the device
  certificate, and the device private key (so AWS can verify the device).
  Both sides authenticate each other; that is the "mutual" part.
- **Initial connect** retries forever with exponential backoff capped at 60
  seconds, plus random jitter so a fleet of devices recovering from an
  outage does not reconnect in lockstep (the thundering herd problem).
- **After the first connect**, paho's background network loop owns
  reconnection, configured with the same bounds via `reconnect_delay_set`.
- **QoS 1** (at least once). The broker must acknowledge each publish;
  `wait_for_publish` turns a missing ack into a `TimeoutError`. The loop in
  `agent.py` catches it, logs, and just tries again next interval. QoS 1 can
  deliver duplicates, which is fine here: a duplicate has the same
  `device_id` and `epoch_ms`, so the DynamoDB `PutItem` overwrites the same
  item and the pipeline deduplicates for free. That is a small example of
  designing for idempotency instead of fighting for exactly-once delivery.

### Lifecycle

`agent.py` runs the loop with a `threading.Event` for shutdown:
`stop.wait(interval)` doubles as the sleep and the wake-up-on-shutdown
mechanism, so SIGTERM from systemd stops the agent within one interval and
`close()` disconnects cleanly. A failed cycle is logged and retried next
interval; the agent never dies because AWS was briefly unreachable. The
systemd unit (`agent/systemd/pi-telemetry-agent.service`) adds
`Restart=on-failure` on top for crashes.

**Concepts:** sysfs thermal zones, config precedence, protocol-based
dependency injection (the tests inject a fake MQTT client and a fake clock),
mutual TLS, exponential backoff with jitter, MQTT QoS levels, idempotency.

## 2. Device identity: X.509 and the CSR flow (`infra/iot.tf`)

AWS IoT Core does not use IAM users or access keys for devices. Each device
authenticates with an X.509 certificate presented during the TLS handshake.
The interesting part is how the certificate is issued:

1. On the Pi: `openssl genrsa` creates a private key, and `openssl req`
   creates a certificate signing request (CSR) from it. The CSR contains the
   public key and identity, never the private key.
2. Terraform reads only the CSR (`aws_iot_certificate.device` with
   `csr = file(...)`) and has AWS IoT sign it.
3. The signed certificate comes back as a Terraform output; the private key
   has never left the device and never enters Terraform state.

This matters because Terraform state is stored in S3 and anyone who can read
state can read anything in it. The alternative resource
(`aws_iot_certificate` without a CSR) generates the key pair on the AWS side
and stores the private key in state. The CSR flow avoids that entirely.

Identity is then wired together with three attachments: the certificate is
attached to the IoT thing (a registry entry for the device), and the IoT
policy is attached to the certificate. Policies attach to certificates, not
things: the certificate is the authenticated principal.

The policy itself is two statements with no wildcards:

- `iot:Connect` only as client id `<device_id>`
- `iot:Publish` only to topic `telemetry/<device_id>`

No subscribe, no receive, no other topics. If this device's key is ever
stolen, the blast radius is: the thief can publish fake telemetry for this
one device. They cannot read other devices' data, cannot subscribe to
anything, and cannot even connect while impersonating a different client id.

**Concepts:** X.509 device authentication, CSR-based issuance and why
private keys should never enter Terraform state, IoT policies vs IAM
policies, least privilege and blast radius.

## 3. Ingest and routing: the IoT rule (`infra/iot_rule.tf`)

Messages arrive at the IoT Core message broker on `telemetry/<device_id>`.
Nothing consumes MQTT directly; instead a topic rule subscribes to
`telemetry/+` (the `+` is a single-level MQTT wildcard) and runs SQL over
every message:

```sql
SELECT *, (timestamp() / 1000) + <ttl_days * 86400> AS expires_at
FROM 'telemetry/+'
```

Two things happen in that one line:

- `SELECT *` passes the payload through unchanged.
- `timestamp()` is the rule engine's processing time in epoch milliseconds;
  dividing by 1000 and adding the retention window computes an `expires_at`
  in epoch seconds. DynamoDB TTL (section 4) wants exactly that. Computing
  it at ingest keeps the device dumb: retention policy is an AWS-side
  concern, and changing `ttl_days` in Terraform changes it for all future
  messages without touching the device.

The rule then fans out to two actions:

- **`dynamodbv2`**: writes the whole message as one item to the telemetry
  table. The `v2` action maps JSON fields to DynamoDB attributes natively;
  the older `dynamodb` action stuffs the payload into a single attribute.
- **`lambda`**: invokes the processor asynchronously with the same payload.

This is fan-out at the routing layer: storage and processing are parallel
consumers, not a chain. If the Lambda has a bug, raw data still lands in
DynamoDB. An `error_action` writes rule failures (say, DynamoDB throttling)
to a CloudWatch log group, otherwise failures would be silent.

Two permission grants make this work, and they point in opposite
directions. The rule's DynamoDB write uses an IAM role that IoT assumes
(identity-based). The Lambda invoke uses a resource-based policy on the
function (`aws_lambda_permission`) allowing principal `iot.amazonaws.com`,
with `source_arn` pinned to this exact rule so no other rule in the account
can invoke it. Lambda invocation across services is conventionally granted
on the function side; this pattern (SNS invoking Lambda, S3 invoking
Lambda, EventBridge invoking Lambda) shows up constantly on the exam.

**Concepts:** IoT rule SQL, MQTT topic wildcards, serverless fan-out,
identity-based vs resource-based policies, `source_arn` scoping, error
actions.

## 4. Storage: DynamoDB key design and TTL (`infra/dynamodb.tf`)

Both tables use the same composite primary key:

- Partition key `device_id` (string): spreads devices across partitions and
  makes "everything about device X" a single-partition operation.
- Sort key `epoch_ms` (number): orders items by time within a device.

This is the canonical time-series key design, and it exists to serve the
access patterns, not the other way round. The two queries the system needs:

- "Latest N readings for a device": `Query` on `device_id` with
  `ScanIndexForward=False, Limit=N`.
- "Readings for a device in a time range": `Query` with
  `epoch_ms BETWEEN a AND b`, which is exactly what the Lambda's rolling
  window does.

Both are `Query` operations that touch one partition and read only the items
they return. Neither ever needs a `Scan`, which reads the whole table and is
the classic DynamoDB cost trap.

Billing is `PAY_PER_REQUEST` (on-demand): no capacity planning, and at one
message a minute the cost is effectively zero. Provisioned capacity only
wins when traffic is high and predictable.

TTL: DynamoDB deletes items whose `expires_at` (epoch seconds) has passed.
Deletion is free, happens in the background, and can lag expiry by up to a
couple of days, which is fine for a cleanup mechanism, not fine if you need
precise cutoffs (then you filter on read too). Raw telemetry expires after
14 days; anomalies live in their own table partly so they can keep a longer
TTL (90 days) without keeping all the raw data that long.

**Concepts:** partition/sort key design from access patterns, Query vs
Scan, on-demand vs provisioned capacity, TTL semantics and their limits.

## 5. Processing: the Lambda (`lambda/src/handler.py`)

The handler does four things in order:

1. **Validate.** Required fields present, `device_id` a non-empty string,
   `epoch_ms` positive, percentage metrics inside plausible ranges. Invalid
   payloads are logged and dropped with `{"status": "invalid"}`, never
   raised: the IoT rule invocation is asynchronous fire-and-forget, so
   raising would only trigger retries of a payload that will never become
   valid.
2. **Aggregate.** Query the telemetry table for this device's last 15
   minutes (the window the IoT rule already wrote to) and compute average
   and max for CPU, memory, and temperature. This is the read pattern the
   sort key was designed for.
3. **Detect.** Compare current metrics against thresholds that arrive as
   environment variables, set by Terraform. Code holds the logic,
   infrastructure holds the tuning; changing a threshold is a `terraform
   apply`, not a code deploy.
4. **Record.** Always emit the anomaly count metric (section 6). If there
   were anomalies, write one record to the anomalies table with the
   triggering values, the aggregates for context, and its own `expires_at`.

Implementation details worth noticing:

- The `boto3.resource` is created lazily and cached in a module global.
  Lambda reuses the process across invocations of a warm container, so
  clients created at module scope or cached like this survive between
  invocations and skip repeated connection setup.
- DynamoDB's number type does not accept Python floats (binary floats lose
  precision); `_to_dynamo` converts them to `Decimal` via their string
  representation.
- The function has no third-party dependencies beyond boto3, which the
  Lambda runtime provides. That keeps the deployment package to a zip of
  `lambda/src/` with no build step (`infra/lambda.tf` zips the directory
  directly). It runs on `arm64` (Graviton), which is around 20 percent
  cheaper per GB-second than x86, at 128 MB with a 15 second timeout.
- The tests (`lambda/tests/`) run against moto, an in-memory AWS mock, so
  `make test-lambda` needs no credentials and no network.

**Concepts:** async Lambda invocation semantics, warm starts and client
caching, environment-variable configuration, Decimal vs float in DynamoDB,
Graviton pricing, testing AWS code with moto.

## 6. Observability: EMF, log groups, optional alarm (`infra/cloudwatch.tf`)

The anomaly metric uses CloudWatch **embedded metric format** (EMF): the
Lambda prints one JSON line with an `_aws` block declaring namespace,
dimensions, and metric names, plus the values. CloudWatch Logs parses that
line and materializes a real metric (`PiTelemetry/AnomalyCount` by
`DeviceId`) from it. Compared to calling `PutMetricData`: no API call
latency inside the handler, no `cloudwatch:PutMetricData` permission on the
role, no per-request API cost, and the log line itself remains as a
debugging record. This is why the handler uses a bare `print` for it: EMF
must be a clean line on stdout.

Both log groups (Lambda logs, IoT rule errors) are declared explicitly in
Terraform rather than letting Lambda create its own on first write. Two
reasons: an explicit group gets `retention_in_days` set from day one
(auto-created groups default to never-expire, which is a slow cost leak),
and Terraform owns it, so `terraform destroy` actually removes it.

The alarm is off by default (`enable_temp_alarm = false`) because it is the
one optional resource with a real price past the free tier. When enabled:
alarm on `Sum(AnomalyCount) >= 1` over 5 minutes, notifying an SNS topic
with an email subscription. `treat_missing_data = "notBreaching"` means a
silent device (nothing published, so no metric datapoints at all) does not
ring the alarm; only actual anomaly reports do.

**Concepts:** embedded metric format vs PutMetricData, log retention and
lifecycle ownership, alarm anatomy (period, evaluation, missing-data
policy), SNS email subscriptions.

## 7. IAM: three principals, three scopes (`infra/iam.tf`, `infra/iot.tf`)

Every actor in the pipeline has its own identity with only its own verbs on
only its own resources:

| Principal | Identity | Can do | Cannot do |
|---|---|---|---|
| The Pi | X.509 cert + IoT policy | Connect as itself, publish to its topic | Subscribe, publish elsewhere, touch AWS APIs |
| IoT rule | IAM role assumed by `iot.amazonaws.com` | `PutItem` on the telemetry table, write its error log group | Read anything, touch the anomalies table |
| Lambda | IAM role assumed by `lambda.amazonaws.com` | `Query` telemetry, `PutItem` anomalies, write its own log group | Write telemetry, read anomalies, `PutMetricData` |

Note the asymmetry between the two tables: the rule can write telemetry but
the Lambda can only read it; the Lambda can write anomalies but nothing can
read them except you. Each role's trust policy (`assume_role_policy`) names
exactly one service principal, and each permission statement names exact
table and log group ARNs, no `Resource: "*"` anywhere. The Lambda role also
deliberately lacks `PutMetricData`: EMF made the permission unnecessary, so
it is absent.

**Concepts:** service roles and trust policies, resource-scoped statements,
noticing which permissions a design lets you delete.

## 8. Terraform structure (`infra/`)

State lives in S3 with a DynamoDB lock table, both created manually outside
this stack. That is deliberate: if the backend were resources inside the
stack, `terraform destroy` would delete the bucket holding the state that
records the destroy. The backend block is empty (`backend "s3" {}`) and
filled at init time from a gitignored `backend.hcl`, keeping bucket names
out of the repo. Versioning on the state bucket gives point-in-time
recovery if state is ever corrupted.

Other conventions in play:

- One file per concern (`iot.tf`, `iot_rule.tf`, `dynamodb.tf`,
  `lambda.tf`, `iam.tf`, `cloudwatch.tf`), so the file list reads as an
  architecture summary.
- Everything account-specific is a variable or a data source. The account
  id comes from `data.aws_caller_identity`, the IoT endpoint from
  `data.aws_iot_endpoint`; nothing is hardcoded, so the stack applies to
  any account.
- `default_tags` on the provider stamps every resource with `Project` and
  `ManagedBy` for cost attribution and cleanup.
- Variables carry `validation` blocks where a bad value would be silently
  harmful (`ttl_days >= 1`).
- Outputs surface exactly what the next step needs: the IoT endpoint and
  signed certificate for the agent config, table and function names for
  verification. The certificate output is marked `sensitive`.

**Concepts:** remote state and locking, why the backend lives outside the
stack, data sources vs hardcoding, default tags, sensitive outputs.

## 9. Failure modes, walked end to end

Tracing failures is the best way to check a design holds together:

- **Network down at the Pi**: the publisher blocks in its backoff loop or
  paho retries in the background; the loop logs each failed cycle and keeps
  going. Data during the outage is lost by design (no on-device queue),
  which is an accepted trade-off for metrics that are only useful fresh.
- **Agent crashes**: systemd restarts it.
- **Broker gets a duplicate (QoS 1)**: same key, idempotent overwrite.
- **Lambda throws or is throttled**: the DynamoDB write already happened in
  parallel; raw data is safe. Async Lambda invocations retry twice.
- **Rule cannot write to DynamoDB**: the error action logs it to the rule
  error log group.
- **Sensor breaks**: implausible temperatures are dropped at the collector;
  a missing metric is valid per the schema and skipped by validation,
  aggregation, and detection alike.
- **Invalid payload reaches the Lambda**: logged, dropped, no retry storm.
- **Storage grows**: it does not; TTL caps both tables by design.

## 10. SAA-C03 mapping

By exam domain:

**Design secure architectures.** Mutual TLS device auth with X.509 and
CSR-based issuance; IoT policies scoped to client id and topic; per-service
IAM roles with single-purpose trust policies and exact-ARN statements;
resource-based vs identity-based policies (the Lambda permission vs the
rule role); secrets kept out of git and out of Terraform state.

**Design resilient architectures.** Decoupling via the rule fan-out
(storage survives processing failures); retries with backoff and jitter;
idempotent writes absorbing at-least-once delivery; async invocation retry
behavior; systemd process supervision at the edge.

**Design high-performing architectures.** DynamoDB key design driven by
access patterns, Query over Scan; serverless end to end, so nothing idles;
arm64 Lambda; warm-start client reuse.

**Design cost-optimized architectures.** On-demand capacity for spiky tiny
workloads; TTL as free data lifecycle management; EMF instead of paid
metric API calls; explicit log retention; the one paid-tier feature (the
alarm) behind an off-by-default flag; free tier boundaries documented in
the README cost table.
