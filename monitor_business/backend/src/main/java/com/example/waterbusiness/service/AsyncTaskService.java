package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.AsyncTaskStatusResponse;
import com.example.waterbusiness.dto.AutoForecastRunNowResponse;
import com.example.waterbusiness.dto.ForecastBatchTaskMessage;
import com.example.waterbusiness.dto.UsgsIvRefreshRequest;
import com.example.waterbusiness.dto.UsgsIvRefreshResultDto;
import com.example.waterbusiness.entity.AsyncTask;
import com.example.waterbusiness.entity.AsyncTaskStatus;
import com.example.waterbusiness.entity.AsyncTaskType;
import com.example.waterbusiness.mq.ForecastBatchMessageDeadLetterException;
import com.example.waterbusiness.repository.AsyncTaskRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.Executor;

@Service
@RequiredArgsConstructor
public class AsyncTaskService {
    private static final int MAX_RETRIES = 2;
    private static final long FORECAST_SINGLE_FLIGHT_LOCK_KEY = 8242001L;

    private final AsyncTaskRepository asyncTaskRepository;
    private final UsgsIvRefreshService usgsIvRefreshService;
    private final AutoForecastBatchService autoForecastBatchService;
    private final AutoForecastSettingsService autoForecastSettingsService;
    private final ObjectMapper objectMapper;
    private final CacheManager cacheManager;
    private final RabbitTemplate rabbitTemplate;
    private final JdbcTemplate jdbcTemplate;

    @Value("${water.mq.forecast.exchange}")
    private String forecastExchange;

    @Value("${water.mq.forecast.routing-key}")
    private String forecastRoutingKey;

    @Qualifier("taskWorkerExecutor")
    private final Executor taskWorkerExecutor;

    public AsyncTaskStatusResponse submitIvRefresh(UsgsIvRefreshRequest request, String idempotencyKeyHeader) {
        String key = normalizeIdempotencyKey(idempotencyKeyHeader);
        UsgsIvRefreshRequest in = request != null ? request : new UsgsIvRefreshRequest();
        if (in.getDays() == null) {
            in.setDays(30);
        }
        TaskCreateOutcome outcome = createTaskOrGetExisting(AsyncTaskType.IV_REFRESH, in, key);
        if (outcome.createdNew()) {
            taskWorkerExecutor.execute(() -> runIvRefreshTask(outcome.task().getTaskId(), in, 0));
        }
        return toResponse(outcome.task(), null);
    }

    @Transactional
    public AsyncTaskStatusResponse submitForecastBatchRunNow(String idempotencyKeyHeader) {
        // DB-level serialization: only one creator enters this critical section at a time.
        jdbcTemplate.query("select pg_advisory_xact_lock(?)", rs -> { }, FORECAST_SINGLE_FLIGHT_LOCK_KEY);

        AsyncTask inFlight = findInFlightForecastBatchTask();
        if (inFlight != null) {
            return toResponse(inFlight, null);
        }

        String key = normalizeIdempotencyKey(idempotencyKeyHeader);
        TaskCreateOutcome outcome = createTaskOrGetExisting(AsyncTaskType.FORECAST_BATCH_RUN_NOW, Map.of(), key);
        if (outcome.createdNew()) {
            publishForecastBatchTask(outcome.task().getTaskId());
        }
        return toResponse(outcome.task(), null);
    }

    private AsyncTask findInFlightForecastBatchTask() {
        List<AsyncTask> rows = asyncTaskRepository.findInFlightTasksForUpdate(
                AsyncTaskType.FORECAST_BATCH_RUN_NOW,
                List.of(AsyncTaskStatus.PENDING, AsyncTaskStatus.RUNNING, AsyncTaskStatus.RETRYING),
                PageRequest.of(0, 1)
        );
        if (rows.isEmpty()) {
            return null;
        }
        return rows.get(0);
    }

    public void consumeForecastBatchTaskFromQueue(String taskId) {
        AsyncTask t = mustGet(taskId);
        if (t.getStatus() == AsyncTaskStatus.RUNNING
                || t.getStatus() == AsyncTaskStatus.RETRYING
                || t.getStatus() == AsyncTaskStatus.CANCELLED
                || t.getStatus() == AsyncTaskStatus.SUCCEEDED
                || t.getStatus() == AsyncTaskStatus.FAILED) {
            return;
        }
        runForecastBatchTask(taskId, 0, true);
        AsyncTask after = mustGet(taskId);
        if (after.getStatus() == AsyncTaskStatus.FAILED) {
            throw new ForecastBatchMessageDeadLetterException(
                    "Forecast batch task failed (taskId=" + taskId + "): " + after.getErrorMessage()
            );
        }
    }

    public AsyncTaskStatusResponse getTask(String taskId) {
        AsyncTask t = asyncTaskRepository.findByTaskId(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在: " + taskId));
        Object result = null;
        if (t.getResultJson() != null && !t.getResultJson().isBlank()) {
            try {
                result = objectMapper.readTree(t.getResultJson());
            } catch (JsonProcessingException ignored) {
                result = null;
            }
        }
        return toResponse(t, result);
    }

    public List<AsyncTaskStatusResponse> listRecent(int limit) {
        int size = Math.max(1, Math.min(limit, 100));
        return asyncTaskRepository.findAll(
                        PageRequest.of(0, size, Sort.by(Sort.Direction.DESC, "createdAt"))
                ).stream()
                .map(t -> toResponse(t, null))
                .toList();
    }

    public AsyncTaskStatusResponse cancelTask(String taskId) {
        AsyncTask t = mustGet(taskId);
        if (t.getStatus() == AsyncTaskStatus.SUCCEEDED || t.getStatus() == AsyncTaskStatus.FAILED || t.getStatus() == AsyncTaskStatus.CANCELLED) {
            return toResponse(t, null);
        }
        LocalDateTime now = LocalDateTime.now();
        t.setStatus(AsyncTaskStatus.CANCELLED);
        t.setCurrentStep("cancelled");
        t.setErrorMessage("Task cancelled by user");
        t.setFinishedAt(now);
        t.setUpdatedAt(now);
        asyncTaskRepository.save(t);
        return toResponse(t, null);
    }

    private record TaskCreateOutcome(AsyncTask task, boolean createdNew) {}

    /**
     * 同一 taskType + Idempotency-Key 只保留一条任务行；重复提交返回已有任务且不再次入队。
     * 若请求体与首次不同，仍以首次落库为准（幂等语义）。
     */
    private TaskCreateOutcome createTaskOrGetExisting(AsyncTaskType type, Object payload, String idempotencyKey) {
        if (idempotencyKey != null) {
            Optional<AsyncTask> existing = asyncTaskRepository.findByTaskTypeAndIdempotencyKey(type, idempotencyKey);
            if (existing.isPresent()) {
                return new TaskCreateOutcome(existing.get(), false);
            }
        }
        LocalDateTime now = LocalDateTime.now();
        AsyncTask t = new AsyncTask();
        t.setTaskId(UUID.randomUUID().toString());
        t.setTaskType(type);
        t.setIdempotencyKey(idempotencyKey);
        t.setStatus(AsyncTaskStatus.PENDING);
        t.setProgressPercent(0);
        t.setRetryCount(0);
        t.setCurrentStep("queued");
        t.setPayloadJson(writeJson(payload));
        t.setCreatedAt(now);
        t.setUpdatedAt(now);
        try {
            return new TaskCreateOutcome(asyncTaskRepository.save(t), true);
        } catch (DataIntegrityViolationException ex) {
            if (idempotencyKey != null) {
                AsyncTask dup = asyncTaskRepository
                        .findByTaskTypeAndIdempotencyKey(type, idempotencyKey)
                        .orElseThrow(() -> ex);
                return new TaskCreateOutcome(dup, false);
            }
            throw ex;
        }
    }

    private static String normalizeIdempotencyKey(String raw) {
        if (raw == null) {
            return null;
        }
        String s = raw.trim();
        if (s.isEmpty()) {
            return null;
        }
        if (s.length() > 128) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key 长度不能超过 128");
        }
        return s;
    }

    private void runIvRefreshTask(String taskId, UsgsIvRefreshRequest request, int attempt) {
        AsyncTask t = mustGet(taskId);
        if (t.getStatus() == AsyncTaskStatus.CANCELLED) {
            return;
        }
        markRunning(t, "refreshing_iv_csv", 10);
        try {
            UsgsIvRefreshResultDto out = usgsIvRefreshService.refreshWithRetry(request);
            markSucceeded(t, out);
        } catch (Exception e) {
            if (!tryScheduleRetry(t, e, () -> runIvRefreshTask(taskId, request, attempt + 1), false)) {
                markFailed(t, e);
            }
        }
    }

    /**
     * @param syncRetry true：在当前线程休眠后重试（MQ 消费路径），便于一次投递内跑完重试并在最终失败时 nack→DLQ；
     *                  false：提交到 taskWorkerExecutor（IV 刷新等 HTTP 触发的异步任务）。
     */
    private void runForecastBatchTask(String taskId, int attempt, boolean syncRetry) {
        AsyncTask t = mustGet(taskId);
        if (t.getStatus() == AsyncTaskStatus.CANCELLED
                || t.getStatus() == AsyncTaskStatus.SUCCEEDED
                || t.getStatus() == AsyncTaskStatus.FAILED) {
            return;
        }
        markRunning(t, "running_batch_forecast", 10);
        try {
            var exec = autoForecastBatchService.executeBatch();
            AutoForecastRunNowResponse body = AutoForecastRunNowResponse.builder()
                    .settings(autoForecastSettingsService.getResponse())
                    .batchResults(exec.batchResults())
                    .build();
            markSucceeded(t, body);
        } catch (Exception e) {
            if (!tryScheduleRetry(t, e, () -> runForecastBatchTask(taskId, attempt + 1, syncRetry), syncRetry)) {
                markFailed(t, e);
            }
        }
    }

    private boolean tryScheduleRetry(AsyncTask t, Exception e, Runnable retryRunner, boolean syncRetry) {
        int retry = t.getRetryCount() != null ? t.getRetryCount() : 0;
        if (retry >= MAX_RETRIES || t.getStatus() == AsyncTaskStatus.CANCELLED) {
            return false;
        }
        LocalDateTime now = LocalDateTime.now();
        int nextRetry = retry + 1;
        t.setStatus(AsyncTaskStatus.RETRYING);
        t.setRetryCount(nextRetry);
        t.setCurrentStep("retrying");
        t.setProgressPercent(Math.max(1, 10 - nextRetry));
        t.setErrorMessage(truncateErr(e.getMessage()));
        t.setUpdatedAt(now);
        asyncTaskRepository.save(t);
        if (syncRetry) {
            try {
                Thread.sleep(800L * nextRetry);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return false;
            }
            if (mustGet(t.getTaskId()).getStatus() == AsyncTaskStatus.CANCELLED) {
                return true;
            }
            retryRunner.run();
            return true;
        }
        taskWorkerExecutor.execute(() -> {
            try {
                Thread.sleep(800L * nextRetry);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            if (mustGet(t.getTaskId()).getStatus() == AsyncTaskStatus.CANCELLED) {
                return;
            }
            retryRunner.run();
        });
        return true;
    }

    private void markRunning(AsyncTask t, String step, int progress) {
        LocalDateTime now = LocalDateTime.now();
        t.setStatus(AsyncTaskStatus.RUNNING);
        t.setCurrentStep(step);
        t.setProgressPercent(progress);
        t.setStartedAt(now);
        t.setUpdatedAt(now);
        asyncTaskRepository.save(t);
    }

    private void markSucceeded(AsyncTask t, Object result) {
        LocalDateTime now = LocalDateTime.now();
        t.setStatus(AsyncTaskStatus.SUCCEEDED);
        t.setCurrentStep("done");
        t.setProgressPercent(100);
        t.setResultJson(writeJson(result));
        t.setErrorMessage(null);
        t.setFinishedAt(now);
        t.setUpdatedAt(now);
        asyncTaskRepository.save(t);
        evictTrendCache();
    }

    private void markFailed(AsyncTask t, Exception e) {
        LocalDateTime now = LocalDateTime.now();
        t.setStatus(AsyncTaskStatus.FAILED);
        t.setCurrentStep("failed");
        t.setErrorMessage(truncateErr(e.getMessage()));
        t.setFinishedAt(now);
        t.setUpdatedAt(now);
        asyncTaskRepository.save(t);
    }

    private AsyncTask mustGet(String taskId) {
        return asyncTaskRepository.findByTaskId(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在: " + taskId));
    }

    private String writeJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            return "{\"_json_error\":true}";
        }
    }

    private static String truncateErr(String s) {
        if (s == null) return "unknown error";
        if (s.length() <= 500) return s;
        return s.substring(0, 497) + "...";
    }

    private void publishForecastBatchTask(String taskId) {
        ForecastBatchTaskMessage message = ForecastBatchTaskMessage.builder()
                .taskId(taskId)
                .taskType(AsyncTaskType.FORECAST_BATCH_RUN_NOW.name())
                .build();
        try {
            rabbitTemplate.convertAndSend(forecastExchange, forecastRoutingKey, message);
        } catch (AmqpException ex) {
            AsyncTask t = mustGet(taskId);
            markFailed(t, ex);
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "任务已创建但投递 MQ 失败，请稍后重试",
                    ex
            );
        }
    }

    private void evictTrendCache() {
        Cache cache = cacheManager.getCache("statsTrend");
        if (cache != null) {
            cache.clear();
        }
    }

    private static AsyncTaskStatusResponse toResponse(AsyncTask t, Object result) {
        return AsyncTaskStatusResponse.builder()
                .taskId(t.getTaskId())
                .taskType(t.getTaskType())
                .status(t.getStatus())
                .progressPercent(t.getProgressPercent())
                .retryCount(t.getRetryCount())
                .currentStep(t.getCurrentStep())
                .errorMessage(t.getErrorMessage())
                .result(result)
                .createdAt(t.getCreatedAt())
                .updatedAt(t.getUpdatedAt())
                .startedAt(t.getStartedAt())
                .finishedAt(t.getFinishedAt())
                .build();
    }
}
