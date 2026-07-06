package com.example.waterbusiness.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

@Configuration
public class AsyncTaskExecutorConfig {

    @Bean(name = "taskWorkerExecutor")
    public Executor taskWorkerExecutor() {
        return Executors.newFixedThreadPool(2);
    }
}
