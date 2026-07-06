# Phase 4: Spring Cloud Gateway (standalone module next to backend).
# Build from monitor_business: docker build -f api-gateway/Dockerfile -t water-api-gateway:local api-gateway
FROM maven:3.9.9-eclipse-temurin-17-alpine AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
RUN addgroup -S spring && adduser -S spring -G spring
COPY --from=build /app/target/api-gateway-*.jar /app/app.jar
USER spring:spring
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
