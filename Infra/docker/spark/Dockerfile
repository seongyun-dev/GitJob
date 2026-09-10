# Project Spark runtime. The base image includes Java, Spark and the Python
# binding; application-specific dependencies can be added here once AI source
# and its lockfile are committed.

ARG SPARK_BASE_IMAGE=apache/spark:3.5.3-scala2.12-java11-python3-ubuntu
FROM ${SPARK_BASE_IMAGE}

USER root

# Structured Streaming reads Kafka through a connector that the base image does
# not ship (verified on the data node: /opt/spark/jars holds no kafka jar).
#
# These are baked in rather than resolved with `--packages` at submit time.
# A streaming query is long-lived and restarts on its own; making every restart
# depend on reaching Maven turns an outage there into a stalled C1 (-112).
#
# The set and the versions are the connector's own resolved dependencies for
# Spark 3.5.3 / Scala 2.12, read from its POM — kafka-clients follows Spark's
# <kafka.version>, so it is 3.4.1 and not the broker's version.
ARG SPARK_KAFKA_VERSION=3.5.3
ARG KAFKA_CLIENTS_VERSION=3.4.1
ARG COMMONS_POOL2_VERSION=2.11.1
ARG MAVEN_BASE=https://repo1.maven.org/maven2

# Each jar is checked against the .sha1 Maven publishes beside it. A silently
# truncated download would otherwise surface much later as a ClassNotFound in
# a running stream.
RUN set -eux; \
    for coord in \
        "org/apache/spark/spark-sql-kafka-0-10_2.12/${SPARK_KAFKA_VERSION}/spark-sql-kafka-0-10_2.12-${SPARK_KAFKA_VERSION}.jar" \
        "org/apache/spark/spark-token-provider-kafka-0-10_2.12/${SPARK_KAFKA_VERSION}/spark-token-provider-kafka-0-10_2.12-${SPARK_KAFKA_VERSION}.jar" \
        "org/apache/kafka/kafka-clients/${KAFKA_CLIENTS_VERSION}/kafka-clients-${KAFKA_CLIENTS_VERSION}.jar" \
        "org/apache/commons/commons-pool2/${COMMONS_POOL2_VERSION}/commons-pool2-${COMMONS_POOL2_VERSION}.jar" \
    ; do \
        name="$(basename "$coord")"; \
        curl -fsSL "${MAVEN_BASE}/${coord}" -o "/opt/spark/jars/${name}"; \
        expected="$(curl -fsSL "${MAVEN_BASE}/${coord}.sha1" | tr -d '[:space:]' | cut -c1-40)"; \
        actual="$(sha1sum "/opt/spark/jars/${name}" | cut -d' ' -f1)"; \
        [ "$expected" = "$actual" ] || { echo "sha1 mismatch for ${name}: ${actual} != ${expected}" >&2; exit 1; }; \
    done

COPY Infra/spark /opt/gitjob/spark
RUN chown -R spark:spark /opt/gitjob/spark
USER spark

WORKDIR /opt/spark/work-dir
