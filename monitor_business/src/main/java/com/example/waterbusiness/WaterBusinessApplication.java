package com.example.waterbusiness;

import com.example.waterbusiness.config.TurbidityThresholdProperties;
import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.config.StatsProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableFeignClients
@EnableScheduling
@EnableConfigurationProperties({WaterAlertProperties.class, StatsProperties.class, TurbidityThresholdProperties.class})
@SpringBootApplication
public class WaterBusinessApplication {

    public static void main(String[] args) {
        SpringApplication.run(WaterBusinessApplication.class, args);
    }
}
