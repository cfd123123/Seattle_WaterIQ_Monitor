package com.example.waterbusiness;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;

/**
 * 批量预测等 MQ 消费者的独立进程入口（不启动 Tomcat）。
 * <p>
 * 运行方式示例：
 * <pre>
 *   java -jar water-business-0.0.1-SNAPSHOT.jar --spring.profiles.active=worker
 * </pre>
 * 或与默认 API 同参，在 IDE 中直接运行本类的 {@code main}。
 */
public final class WaterBusinessWorkerApplication {

    private WaterBusinessWorkerApplication() {}

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(WaterBusinessApplication.class);
        app.setWebApplicationType(WebApplicationType.NONE);
        app.setAdditionalProfiles("worker");
        app.run(args);
    }
}
