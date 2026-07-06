package com.example.waterbusiness.mq;

/**
 * 批量预测 MQ 消费在业务重试耗尽后仍失败时抛出，配合队列死信配置将消息送入 DLQ。
 */
public class ForecastBatchMessageDeadLetterException extends RuntimeException {

    public ForecastBatchMessageDeadLetterException(String message) {
        super(message);
    }
}
