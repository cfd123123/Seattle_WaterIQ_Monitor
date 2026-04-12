package com.example.waterbusiness.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * Custom business metrics ({@code water.*}), complementing Actuator JVM/HTTP.
 */
@Component
public class WaterBusinessMetrics {

    private static final List<String> POLLUTION_LEVEL_TAGS = List.of(
            "excellent", "good", "moderate", "poor", "very_poor", "unknown"
    );
    private static final List<String> SEVERITY_TAGS = List.of("low", "medium", "high", "unknown");

    private final MeterRegistry registry;
    private final Timer aiPredictSuccess;
    private final Timer aiPredictFailure;
    private final Map<String, Counter> checksCompletedByLevel = new HashMap<>();
    private final Map<String, Counter> alertsCreatedBySeverityAndLevel = new HashMap<>();
    private final Counter batchItemsSuccess;
    private final Counter batchItemsFailure;

    public WaterBusinessMetrics(MeterRegistry registry) {
        this.registry = registry;
        this.aiPredictSuccess = Timer.builder("water.ai.predict")
                .tag("outcome", "success")
                .description("Feign AI /predict success latency")
                .publishPercentileHistogram()
                .register(registry);
        this.aiPredictFailure = Timer.builder("water.ai.predict")
                .tag("outcome", "failure")
                .description("Feign AI /predict failure latency")
                .publishPercentileHistogram()
                .register(registry);
        for (String level : POLLUTION_LEVEL_TAGS) {
            checksCompletedByLevel.put(
                    level,
                    Counter.builder("water.checks.completed")
                            .tag("pollution_level", level)
                            .description("Checks completed by pollution level")
                            .register(registry)
            );
        }
        for (String sev : SEVERITY_TAGS) {
            for (String pl : POLLUTION_LEVEL_TAGS) {
                alertsCreatedBySeverityAndLevel.put(
                        alertKey(sev, pl),
                        Counter.builder("water.alerts.created")
                                .tag("severity", sev)
                                .tag("pollution_level", pl)
                                .description("Alerts written to alert_event by severity and pollution level")
                                .register(registry)
                );
            }
        }
        this.batchItemsSuccess = Counter.builder("water.check.batch.items")
                .tag("outcome", "success")
                .description("Batch check per-item successes")
                .register(registry);
        this.batchItemsFailure = Counter.builder("water.check.batch.items")
                .tag("outcome", "failure")
                .description("Batch check per-item failures")
                .register(registry);
    }

    public void recordPredictDuration(long durationMs, boolean success) {
        (success ? aiPredictSuccess : aiPredictFailure).record(durationMs, TimeUnit.MILLISECONDS);
    }

    public void recordCheckCompleted(String pollutionLevel) {
        String level = normalizePollutionLevel(pollutionLevel);
        Counter counter = checksCompletedByLevel.get(level);
        if (counter == null) {
            counter = checksCompletedByLevel.get("unknown");
        }
        counter.increment();
    }

    public void recordAlertCreated(String severity, String pollutionLevel) {
        String sev = normalizeSeverity(severity);
        String pl = normalizePollutionLevel(pollutionLevel);
        Counter counter = alertsCreatedBySeverityAndLevel.get(alertKey(sev, pl));
        if (counter == null) {
            counter = registry.counter(
                    "water.alerts.created",
                    "severity", sev,
                    "pollution_level", pl
            );
        }
        counter.increment();
    }

    public void recordBatchItemSuccess() {
        batchItemsSuccess.increment();
    }

    public void recordBatchItemFailure() {
        batchItemsFailure.increment();
    }

    private static String normalizePollutionLevel(String pollutionLevel) {
        if (pollutionLevel == null || pollutionLevel.isBlank()) {
            return "unknown";
        }
        return pollutionLevel.trim().toLowerCase(Locale.ROOT).replace(' ', '_');
    }

    private static String normalizeSeverity(String severity) {
        if (severity == null || severity.isBlank()) {
            return "unknown";
        }
        return severity.trim().toLowerCase(Locale.ROOT);
    }

    private static String alertKey(String severity, String pollutionLevel) {
        return severity + "|" + pollutionLevel;
    }
}
