package com.example.waterbusiness.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.HashMap;
import java.util.Map;

@Configuration
public class RabbitMqConfig {

    @Bean
    public TopicExchange forecastBatchExchange(@Value("${water.mq.forecast.exchange}") String exchangeName) {
        return new TopicExchange(exchangeName, true, false);
    }

    /**
     * 死信交换机：业务队列拒绝且不 requeue 的消息进入此处，再路由到 DLQ。
     */
    @Bean
    public TopicExchange forecastBatchDlxExchange(@Value("${water.mq.forecast.dlx-exchange}") String dlxName) {
        return new TopicExchange(dlxName, true, false);
    }

    @Bean
    public Queue forecastBatchDlqQueue(@Value("${water.mq.forecast.dlq-queue}") String dlqQueueName) {
        return new Queue(dlqQueueName, true, false, false);
    }

    @Bean
    public Binding forecastBatchDlqBinding(
            Queue forecastBatchDlqQueue,
            TopicExchange forecastBatchDlxExchange,
            @Value("${water.mq.forecast.dlq-routing-key}") String dlqRoutingKey
    ) {
        return BindingBuilder.bind(forecastBatchDlqQueue).to(forecastBatchDlxExchange).with(dlqRoutingKey);
    }

    @Bean
    public Queue forecastBatchQueue(
            @Value("${water.mq.forecast.queue}") String queueName,
            @Value("${water.mq.forecast.dlx-exchange}") String dlxExchangeName,
            @Value("${water.mq.forecast.dlq-routing-key}") String dlqRoutingKey
    ) {
        Map<String, Object> args = new HashMap<>(2);
        args.put("x-dead-letter-exchange", dlxExchangeName);
        args.put("x-dead-letter-routing-key", dlqRoutingKey);
        return new Queue(queueName, true, false, false, args);
    }

    @Bean
    public Binding forecastBatchBinding(
            Queue forecastBatchQueue,
            TopicExchange forecastBatchExchange,
            @Value("${water.mq.forecast.routing-key}") String routingKey
    ) {
        return BindingBuilder.bind(forecastBatchQueue).to(forecastBatchExchange).with(routingKey);
    }

    @Bean
    public MessageConverter rabbitMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }
}
