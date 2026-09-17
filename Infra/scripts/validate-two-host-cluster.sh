#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
DATA_TS_IP="${DATA_TS_IP:-100.64.0.10}"
SERVICE_TS_IP="${SERVICE_TS_IP:-100.64.0.11}"
SERVICE_DN_REGISTRATION_IP="${SERVICE_DN_REGISTRATION_IP:-172.18.0.1}"
CLUSTER_WORKER_PROJECT_NAME="${CLUSTER_WORKER_PROJECT_NAME:-gitjob-cluster-worker}"
export DATA_TS_IP SERVICE_TS_IP SERVICE_DN_REGISTRATION_IP CLUSTER_WORKER_PROJECT_NAME

data_render="$(mktemp)"
worker_render="$(mktemp)"
weekly_render="$(mktemp)"
trap 'rm -f "$data_render" "$worker_render" "$weekly_render"' EXIT

cd "$REPO_ROOT"

# Cluster files must fail closed when their Tailscale addresses are absent.
if env -u DATA_TS_IP -u SERVICE_TS_IP docker compose --project-directory . \
  --project-name "$CLUSTER_WORKER_PROJECT_NAME" \
  --env-file .env.example -f Infra/compose/compose.ec2-cluster-worker.yaml \
  --profile hdfs-worker config --quiet >/dev/null 2>&1; then
  echo "cluster worker unexpectedly accepted missing Tailscale addresses" >&2
  exit 1
fi

# Existing paths must continue to render after Phase 1.
docker compose --project-directory . --env-file .env.example \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  --profile core --profile app config --quiet
SPARK_EXECUTOR_CORES=1 SPARK_CORES_MAX=2 \
docker compose --project-directory . --env-file .env.example \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data config --quiet

SPARK_EXECUTOR_CORES=1 SPARK_CORES_MAX=2 \
docker compose --project-directory . --env-file .env.example \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data-cluster.yaml \
  --profile data config --format json > "$data_render"
docker compose --project-directory . --env-file .env.example \
  --project-name "$CLUSTER_WORKER_PROJECT_NAME" \
  -f Infra/compose/compose.ec2-cluster-worker.yaml \
  --profile hdfs-worker --profile spark-worker config --format json > "$worker_render"
WEEKLY_CONSUMER_KAFKA_BOOTSTRAP="$SERVICE_TS_IP:9094" \
WEEKLY_CONSUMER_GROUP=gitjob-weekly-trend-prod-v1 \
WEEKLY_CONSUMER_WEBHDFS_URL="http://$DATA_TS_IP:9870/webhdfs/v1" \
WEEKLY_CONSUMER_DATANODE_HOSTS="$DATA_TS_IP:9864=$DATA_TS_IP:9864,$SERVICE_TS_IP:9864=$SERVICE_TS_IP:9864" \
WEEKLY_CONSUMER_POSTGRES_HOST="$SERVICE_TS_IP" \
docker compose --project-directory . --env-file .env.example \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2.yaml \
  -f Infra/compose/compose.weekly-host.yaml \
  --profile weekly config --format json > "$weekly_render"

# An option-less operational invocation must remain scoped to Phase 4. Spark
# Worker-2 is enabled only by an explicit Phase 7 profile selection.
default_worker_services="$(
  docker compose --project-directory . --env-file .env.example \
    --project-name "$CLUSTER_WORKER_PROJECT_NAME" \
    -f Infra/compose/compose.ec2-cluster-worker.yaml \
    --profile hdfs-worker config --services
)"
grep -Fqx 'CLUSTER_WORKER_PROFILES=hdfs-worker' .env.example
grep -Fq 'CLUSTER_WORKER_PROFILES="${CLUSTER_WORKER_PROFILES:-hdfs-worker}"' \
  Infra/scripts/cluster-worker.sh
diff -u - <(printf '%s\n' hdfs-datanode4-data-init hdfs-datanode4) \
  <<< "$default_worker_services"

python3 - "$data_render" "$worker_render" "$weekly_render" "$DATA_TS_IP" "$SERVICE_TS_IP" \
  "$SERVICE_DN_REGISTRATION_IP" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
worker = json.load(open(sys.argv[2], encoding="utf-8"))
weekly = json.load(open(sys.argv[3], encoding="utf-8"))
data_ip, service_ip, service_registration_ip = sys.argv[4:7]

assert "weekly-trend-consumer" not in data["services"]
weekly_consumer = weekly["services"]["weekly-trend-consumer"]
assert weekly_consumer["profiles"] == ["weekly"]
assert weekly_consumer["network_mode"] == "host"
assert weekly_consumer["environment"]["WEEKLY_ACTIVITY_CONSUMER_GROUP"] == "gitjob-weekly-trend-prod-v1"
assert weekly_consumer["environment"]["WEBHDFS_URL"] == f"http://{data_ip}:9870/webhdfs/v1"

namenode_env = data["services"]["hdfs-namenode"]["environment"]
assert namenode_env["HDFS-SITE.XML_dfs.client.use.datanode.hostname"] == "true"
assert namenode_env["SERVICE_DN_REGISTRATION_IP"] == service_registration_ip

for name, ports in {
    "hdfs-datanode": (9864, 9866, 9867),
    "hdfs-datanode2": (9874, 9876, 9877),
    "hdfs-datanode3": (9884, 9886, 9887),
}.items():
    service = data["services"][name]
    assert service["network_mode"] == "host"
    assert not service.get("ports") and not service.get("networks")
    env = service["environment"]
    assert env["HDFS-SITE.XML_dfs.client.use.datanode.hostname"] == "true"
    assert env["HDFS-SITE.XML_dfs.datanode.use.datanode.hostname"] == "true"
    assert env["HDFS-SITE.XML_dfs.datanode.http.address"] == f"{data_ip}:{ports[0]}"
    assert env["HDFS-SITE.XML_dfs.datanode.address"] == f"{data_ip}:{ports[1]}"
    assert env["HDFS-SITE.XML_dfs.datanode.ipc.address"] == f"{data_ip}:{ports[2]}"

assert data["services"]["spark-master"]["network_mode"] == "host"
assert data["services"]["spark-worker"]["network_mode"] == "host"

c1_command = data["services"]["spark-c1-archiver"]["command"]
assert "spark.executor.cores=1" in c1_command
assert "spark.cores.max=2" in c1_command
assert c1_command[c1_command.index("--master") + 1] == "spark://spark-master:7077"
assert c1_command[c1_command.index("--deploy-mode") + 1] == "client"
assert c1_command[c1_command.index("--topics") + 1] == "github.events,so.raw"
assert c1_command[c1_command.index("--parquet-root") + 1] == "hdfs:///gitjob/parquet"
assert c1_command[c1_command.index("--checkpoint-root") + 1] == "hdfs:///gitjob/checkpoints"
assert "spark.driver.bindAddress=0.0.0.0" in c1_command
assert "spark.driver.host=spark-c1-archiver" in c1_command
assert "spark.hadoop.dfs.client.use.datanode.hostname=true" in c1_command
assert "spark.hadoop.dfs.replication=2" in c1_command
assert "spark.hadoop.fs.defaultFS=hdfs://hdfs-namenode:8020" in c1_command

expected = {"hdfs-datanode4-data-init", "hdfs-datanode4", "spark-worker2"}
assert set(worker["services"]) == expected
assert worker["name"] == "gitjob-cluster-worker"
dn4 = worker["services"]["hdfs-datanode4"]
sw2 = worker["services"]["spark-worker2"]
assert dn4["network_mode"] == sw2["network_mode"] == "host"
assert not dn4.get("ports") and not dn4.get("networks")
assert not sw2.get("ports") and not sw2.get("networks")
assert dn4["environment"]["HDFS-SITE.XML_dfs.datanode.address"] == f"{service_ip}:9866"
assert dn4["environment"]["HDFS-SITE.XML_dfs.client.use.datanode.hostname"] == "true"
assert dn4["environment"]["HDFS-SITE.XML_dfs.datanode.use.datanode.hostname"] == "true"
assert any(
    mount["target"] == "/opt/gitjob/hadoop/check-datanode-live.awk"
    and mount["read_only"]
    for mount in dn4["volumes"]
)
assert sw2["environment"]["SPARK_MASTER_URL"] == f"spark://{data_ip}:7077"
assert worker["volumes"]["hdfs-datanode4-data"]["name"] == "gitjob-cluster-worker-hdfs-datanode4-data"
print("two-host cluster Compose assertions: PASS")
PY

# The split Jenkins path must preserve the active two-host overlay through
# preflight, start, healthcheck, and final verification.
[[ "$(grep -c 'compose\.ec2-data-cluster\.yaml' Infra/scripts/deploy.sh)" -eq 5 ]]
if grep -qE 'compose\.ec2-data\.yaml([^.-]|$)' Infra/scripts/deploy.sh; then
  echo "split deploy still references the legacy data overlay" >&2
  exit 1
fi

# Repository analysis must not be started before its explicitly owned schema
# exists, and a restart loop must make both health gates fail closed.
grep -Fq 'PROFILES=core bash Infra/scripts/repo-analysis-migrate.sh' Infra/scripts/deploy.sh
grep -Fq 'PROFILES=core bash Infra/scripts/kafka-topics.sh' Infra/scripts/deploy.sh
grep -Fq 'spark-worker worker analysis-worker collector' Infra/scripts/healthcheck.sh
grep -Fq 'analysis-worker-ready' Infra/scripts/verify-deployment.sh
grep -Fq 'analysis-result' Infra/scripts/verify-deployment.sh
grep -Fq 'backend-compute' Infra/scripts/verify-deployment.sh
grep -Fq 'analysis-personal' Infra/scripts/verify-deployment.sh
grep -Fq 'profiles: !override [weekly]' Infra/compose/compose.ec2-data-cluster.yaml
grep -Fq 'remove_legacy_data_weekly_consumer' Infra/scripts/deploy.sh
grep -Fq 'start_service_weekly_consumer' Infra/scripts/deploy.sh
grep -Fq 'weekly-consumer-placement' Infra/scripts/verify-deployment.sh
for topic in requests results dlq results.dlq; do
  grep -Fq "gitjob.repository-analysis.${topic}.v1:3" Infra/scripts/kafka-topics.sh
done
# v3 결과 토픽은 .v1 로 끝나지 않아 위 루프에 들어가지 않는다. 빠지면 워커가
# 기동하지 못하거나 registry-20260911.3/.4 결과가 도달하지 않는다.
grep -Fq "gitjob.repository-analysis.results.v3:3" Infra/scripts/kafka-topics.sh

live_report="$({
  printf '%s\n' 'Live datanodes (4):'
  printf '%s\n' 'Name: 172.18.0.1:9866'
  printf '%s\n' "Hostname: $SERVICE_TS_IP"
})"
dead_only_report="$({
  printf '%s\n' 'Live datanodes (3):'
  printf '%s\n' 'Name: 100.64.0.10:9866'
  printf '%s\n' 'Hostname: 100.64.0.10'
  printf '%s\n' 'Dead datanodes (1):'
  printf '%s\n' 'Name: 172.18.0.1:9866'
  printf '%s\n' "Hostname: $SERVICE_TS_IP"
})"
awk -v expected_hostname="$SERVICE_TS_IP" -v expected_port=9866 \
  -f Infra/hadoop/check-datanode-live.awk <<< "$live_report"
if awk -v expected_hostname="$SERVICE_TS_IP" -v expected_port=9866 \
  -f Infra/hadoop/check-datanode-live.awk <<< "$dead_only_report"; then
  echo "DataNode live check accepted a hostname found only in the dead section" >&2
  exit 1
fi

DATA_TS_IP="$DATA_TS_IP" SERVICE_TS_IP="$SERVICE_TS_IP" \
SERVICE_DN_REGISTRATION_IP="$SERVICE_DN_REGISTRATION_IP" \
  bash Infra/hadoop/topology.sh "$DATA_TS_IP" "$SERVICE_TS_IP" \
    "$SERVICE_DN_REGISTRATION_IP" 203.0.113.1 \
  | diff -u - <(printf '/rack-a\n/rack-b\n/rack-b\n/default-rack\n')

# The shared Spark helper must preserve single-host defaults, derive safe
# two-host defaults from DATA_TS_IP, and still honor explicit overrides.
(
  ENV_FILE=.env.example
  # shellcheck source=/dev/null
  source Infra/scripts/_lib.sh

  unset DATA_TS_IP
  spark_submit_network_args
  [[ "${SPARK_NETWORK_ARGS[*]}" == \
    "--conf spark.driver.bindAddress=0.0.0.0 --conf spark.driver.host=spark-worker --conf spark.hadoop.dfs.client.use.datanode.hostname=true" ]]

  DATA_TS_IP="100.64.0.10"
  spark_submit_network_args
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.host=$DATA_TS_IP"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.bindAddress=$DATA_TS_IP"* ]]

  SPARK_DRIVER_HOST="100.64.0.20"
  SPARK_DRIVER_BIND_ADDRESS="100.64.0.21"
  SPARK_DRIVER_PORT=40001
  SPARK_DRIVER_BLOCK_MANAGER_PORT=40002
  SPARK_EXECUTOR_BLOCK_MANAGER_PORT=41000
  SPARK_PORT_MAX_RETRIES=15
  SPARK_EXECUTOR_CORES=1
  SPARK_CORES_MAX=2
  spark_submit_network_args
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.host=100.64.0.20"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.bindAddress=100.64.0.21"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == \
    *"spark.hadoop.dfs.client.use.datanode.hostname=true"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.port=40001"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.driver.blockManager.port=40002"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.blockManager.port=41000"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.port.maxRetries=15"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.executor.cores=1"* ]]
  [[ "${SPARK_NETWORK_ARGS[*]}" == *"spark.cores.max=2"* ]]
)

echo "two-host cluster static validation: PASS"
