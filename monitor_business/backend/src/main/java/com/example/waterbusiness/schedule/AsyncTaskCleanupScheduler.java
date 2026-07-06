package com.example.waterbusiness.schedule;

import com.example.waterbusiness.entity.AsyncTaskStatus;
import com.example.waterbusiness.repository.AsyncTaskRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Periodically deletes old async task rows to keep the table bounded.
 * Keeps only recent history and avoids deleting in-flight tasks.
 */
@Component
@RequiredArgsConstructor
public class AsyncTaskCleanupScheduler {

    private static final Logger log = LoggerFactory.getLogger(AsyncTaskCleanupScheduler.class);

    private final AsyncTaskRepository asyncTaskRepository;

    @Value("${water.async-task-retention.enabled:true}")
    private boolean enabled;

    @Value("${water.async-task-retention.days:7}")
    private int retentionDays;

    @Scheduled(cron = "${water.async-task-retention.cron:0 20 3 * * ?}")
    @Transactional
    public void cleanupOldAsyncTasks() {
        if (!enabled) {
            return;
        }
        int days = Math.max(1, retentionDays);
        LocalDateTime cutoff = LocalDateTime.now().minusDays(days);
        int deleted = asyncTaskRepository.deleteByCreatedAtBeforeAndStatusIn(
                cutoff,
                List.of(AsyncTaskStatus.SUCCEEDED, AsyncTaskStatus.FAILED, AsyncTaskStatus.CANCELLED)
        );
        if (deleted > 0) {
            log.info("async_task cleanup deleted {} rows older than {} days", deleted, days);
        }
    }
}

