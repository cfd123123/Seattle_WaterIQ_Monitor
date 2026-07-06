package com.example.waterbusiness;

import com.example.waterbusiness.config.TurbidityRiskForecastProperties;
import com.example.waterbusiness.config.TurbidityStateProperties;
import com.example.waterbusiness.config.TurbidityThresholdProperties;
import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.config.StatsProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.amqp.rabbit.annotation.EnableRabbit;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.cache.annotation.EnableCaching;

@EnableFeignClients
@EnableScheduling
@EnableCaching
@EnableRabbit
@EnableConfigurationProperties({
        WaterAlertProperties.class,
        StatsProperties.class,
        TurbidityThresholdProperties.class,
        TurbidityStateProperties.class,
        TurbidityRiskForecastProperties.class
})
@SpringBootApplication
public class WaterBusinessApplication {

    public static void main(String[] args) {
        SpringApplication.run(WaterBusinessApplication.class, args);
    }
}
