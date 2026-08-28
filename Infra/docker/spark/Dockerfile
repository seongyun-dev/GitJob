# Project Spark runtime. The base image includes Java, Spark and the Python
# binding; application-specific dependencies can be added here once AI source
# and its lockfile are committed.

ARG SPARK_BASE_IMAGE=apache/spark:3.5.3-scala2.12-java11-python3-ubuntu
FROM ${SPARK_BASE_IMAGE}

USER root
COPY Infra/spark /opt/gitjob/spark
RUN chown -R spark:spark /opt/gitjob/spark
USER spark

WORKDIR /opt/spark/work-dir
