package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.ForecastBatchTaskMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@Profile("worker")
@RequiredArgsConstructor
public class AsyncTaskMqConsumer {

    private final AsyncTaskService asyncTaskService;

    @RabbitListener(queues = "${water.mq.forecast.queue}")
    public void consumeForecastBatch(ForecastBatchTaskMessage message) {
        if (message == null || message.taskId() == null || message.taskId().isBlank()) {
            log.warn("Skip empty forecast batch task message");
            return;
        }
        asyncTaskService.consumeForecastBatchTaskFromQueue(message.taskId());
    }
}
