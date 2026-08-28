# Assumed contract: BE is a Gradle Spring Boot application targeting Java 21.
# The application source is intentionally outside this infrastructure change.

FROM eclipse-temurin:21-jdk-jammy AS build

WORKDIR /workspace/BE
COPY BE/ ./
RUN chmod +x ./gradlew \
  && ./gradlew --no-daemon clean bootJar \
  && jar_file="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' | head -n 1)" \
  && test -n "$jar_file" \
  && cp "$jar_file" /tmp/gitjob-backend.jar

FROM eclipse-temurin:21-jre-jammy

RUN apt-get update \
  && apt-get install --no-install-recommends --yes curl \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=build /tmp/gitjob-backend.jar /app/app.jar

ENV SERVER_PORT=8080
EXPOSE 8080
USER appuser
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
