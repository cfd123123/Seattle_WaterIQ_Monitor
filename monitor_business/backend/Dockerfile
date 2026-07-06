# 同一镜像：默认命令启动 API（HTTP + MQ Producer）；compose 中覆盖 command 启动 Worker（MQ Consumer）
# 构建：在 monitor_business 目录执行 docker build -f backend/Dockerfile -t water-business:local backend
FROM maven:3.9.9-eclipse-temurin-17-alpine AS build
WORKDIR /app
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
RUN addgroup -S spring && adduser -S spring -G spring
COPY --from=build /app/target/water-business-*.jar /app/app.jar
USER spring:spring
EXPOSE 8080 8088
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
